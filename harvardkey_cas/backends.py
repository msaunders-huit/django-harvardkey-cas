import logging

from django.contrib.auth import get_user_model
from django_cas_ng.backends import CASBackend
from django_cas_ng.utils import get_cas_client

logger = logging.getLogger(__name__)


class CASAuthBackend(CASBackend):
    """
    By default, the ``authenticate`` method creates ``User`` objects for
    usernames that don't already exist in the database.  Subclasses can disable
    this behavior by setting the ``create_unknown_user`` attribute to
    ``False``.
    """
    # Create a User object if not already in the database?
    create_unknown_user = True

    def authenticate(self, request, ticket, service):
        """
        Verifies CAS ticket and gets or creates User object

        The user ID passed as ``username`` is considered trusted.  This
        method simply returns the ``User`` object with the given user ID,
        creating a new ``User`` object if ``create_unknown_user`` is ``True``.

        Returns None if ``create_unknown_user`` is ``False`` and a ``User``
        object with the given username is not found in the database.
        """

        client = get_cas_client(service_url=service)
        username, attributes, pgtiou = client.verify_ticket(ticket)
        if attributes and request:
            request.session['user_attributes'] = attributes
            logger.debug('fetched user attributes from CAS %s' % (attributes))

        authenticationType = attributes.get('authenticationType')
        logger.debug('authenticationType =%s' % (authenticationType))

        if not username:
            return None

        username = self.clean_username(username)
        logger.debug('authen_userid is type %s, cleaned username is %s' %
                     (authenticationType, username))
        # logger.debug('cleaned username is type %s' % type(username))
        UserModel = get_user_model()
        user = None

        # Note that this could be accomplished in one try-except clause, but
        # instead we use get_or_create when creating unknown users since it has
        # built-in safeguards for multiple threads.
        if self.create_unknown_user:
            user, created = UserModel.objects.get_or_create(**{
                UserModel.USERNAME_FIELD: username
            })
            if created:
                logger.debug('authenticate created a new user for %s' % username)
            else:
                logger.debug('authenticate found an existing user for %s' % username)

        else:
            logger.debug('automatic new user creation is turned OFF! just try to find and existing record')
            try:
                user = UserModel.objects.get_by_natural_key(username)
            except UserModel.DoesNotExist:
                logger.debug('authenticate could not find user %s' % username)
                pass

        user = self.configure_user(user, request)
        logger.debug('after configuring user with attributes %s, %s, %s' %
                     (user.last_name, user.first_name, user.email))
        return user

    def configure_user(self, user, request):
        """
        Configures a user after creation and returns the updated user.
        By default, returns the user unmodified.

        In this implementation, we fetch the user's attributes being passed
        from the CAS server and we set the user's first_name, last_name and
        email and also the groups that the user is a member of
        """

        attributes = request.session.get('user_attributes', {})

        if attributes:
            try:
                logger.debug('configuring user attributes for user  %s' % user.username)
                first_name = attributes.get('givenName', '')
                last_name = attributes.get('sn', '')
                email = attributes.get('mail', '')
                user.first_name = first_name[0] if type(first_name) is list else first_name
                user.last_name = last_name[0] if type(last_name) is list else last_name
                user.email = email[0] if type(email) is list else email
                user.save()
                logger.debug('after saving user with attributes %s, %s, %s'
                             % (user.last_name, user.first_name, user.email))

            except Exception as ex:
                logger.error('Exception retrieving person attributes, attributes received: {}'.format(attributes))

            # fetch the user's groups and add them to the session
            try:
                memberOf = attributes.get('memberOf')
                group_ids = None

                if memberOf:
                    if type(memberOf) is list:
                        group_ids = memberOf
                    else:
                        group_ids = list(map(str.strip, memberOf.strip("[]").split(',')))

                    if group_ids:
                        request.session['USER_GROUPS'] = group_ids
                        logger.debug(">>> storing groups for user %s in session "
                                    "%s" % (user.username, group_ids))
                else:
                    logger.warning('No user groups from CAS handshake')
            except Exception as ex:
                logger.error('could not load user groups, ex=%s' % ex)

        else:
            logger.warn(" no user attributes found in CAS response")

        return user
