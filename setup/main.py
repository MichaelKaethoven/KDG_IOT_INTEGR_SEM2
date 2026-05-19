#
#  GoogleFindMyTools - A set of tools to interact with the Google Find My API
#  Copyright © 2024 Leon Böttger. All rights reserved.
#

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'libs'))

from SpotApi.CreateBleDevice.create_ble_device import register_esp32

if __name__ == '__main__':

    register_esp32()