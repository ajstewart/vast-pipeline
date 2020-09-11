import logging
import requests

from typing import Tuple, Dict

from django.conf import settings
from django.contrib.auth.models import User
from social_django.models import UserSocialAuth


logger = logging.getLogger(__name__)


def create_admin_user(uid: int, response: Dict, details: Dict, user: User,
    social: UserSocialAuth , *args: Tuple, **kwargs: Dict) -> Dict:
    """
    Give Django admin privileges to a user who login via GitHub and belong to
    a specific team. The parameters are as per python-social-auth docs
    https://python-social-auth.readthedocs.io/en/latest/pipeline.html#extending-the-pipeline

    Parameters
    ----------
    uid : int
        user id
    response : Dict
        request dictionary
    details : Dict
        user details generated by the backend
    user : User
        Django user model object
    social : UserSocialAuth
        Social auth user model object
    *args : Tuple
        other arguments
    **kwargs : Dict
        other keyword arguments

    Returns
    -------
    Dict
        return a dictionary with the Django User object in it or nothing
    """
    # assume github-org backend, add <if backend.name == 'github-org'>
    # if other backend are implemented
    admin_team = settings.SOCIAL_AUTH_GITHUB_ADMIN_TEAM
    usr = response.get('login', '')
    if (usr != '' and admin_team != '' and user and not user.is_staff and
        not user.is_superuser):
        logger.info('Trying to add Django admin privileges to user')
        # check if github user belong to admin team
        org = settings.SOCIAL_AUTH_GITHUB_ORG_NAME
        header = {
            'Authorization': f"token {response.get('access_token', '')}"
        }
        url = (
            f'https://api.github.com/orgs/{org}/teams/{admin_team}'
            f'/memberships/{usr}'
        )
        resp = requests.get(url, headers=header)
        if resp.ok:
            # add user to admin
            user.is_superuser = True
            user.is_staff = True
            user.save()
            logger.info('Django admin privileges successfully added to user')
            return {'user': user}
        logger.info(f'GitHub request failed, reason: {resp.reason}')

        pass

    pass


def debug(strategy, backend, uid, response, details, user, social, *args,
    **kwargs):
    # TODO: fix arg type and docstring as above
    print(response)
    pass


def load_github_avatar(response: Dict, social: UserSocialAuth, *args: Tuple,
    **kwargs: Dict) -> Dict:
    """
    Add GitHub avatar url to the extra data stored by social_django app

    Parameters
    ----------
    response : Dict
        request dictionary
    social : UserSocialAuth
        Social auth user model object
    *args : Tuple
        other arguments
    **kwargs : Dict
        other keyword arguments

    Returns
    -------
    Dict
        return a dictionary with the Social auth user object in it or nothing
    """
    # assume github-org backend, add <if backend.name == 'github-org'>
    # if other backend are implemented
    # if social and social.get('extra_data', None)
    # print(vars(social))
    if 'avatar_url' not in social.extra_data:
        logger.info('Adding GitHub avatar url to user extra data')
        social.extra_data['avatar_url'] = response['avatar_url']
        social.save()
        return {'social': social}
    pass
