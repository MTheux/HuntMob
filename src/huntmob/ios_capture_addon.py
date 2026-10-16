"""Capture on the dedicated iOS listener; never write into an Android lab."""
import os
import re
from huntmob.network_capture import NetworkCapture


class IosCapture(NetworkCapture):
    user_agent_markers = ('cfnetwork','darwin','iphone','mobile','huntmob')

    def active_lab(self):
        value=os.environ.get('HUNTMOB_IOS_CAPTURE_LAB','')
        if not re.fullmatch(r'ios_[a-f0-9]{32}',value):
            raise ValueError('Owned iOS capture namespace required')
        return value


addons=[IosCapture()]
