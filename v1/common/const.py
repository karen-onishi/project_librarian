"""
Constant types in Python.
"""


class _const:
    class ConstError(TypeError):
        pass

    def __setattr__(self, name, value):
        if name in self.__dict__:
            raise self.ConstError("Can't rebind const (%s)" % name)
        self.__dict__[name] = value


import os
import sys

sys.modules[__name__] = _const()

from . import const
from common.utils import strtobool


#####################
## for Common
#####################
const.PROJECT_ID = os.environ.get("PROJECT_ID")
const.LOCATION = os.environ.get("LOCATION", "us-central1")
const.IS_LOCAL = strtobool(os.environ.get("IS_LOCAL", "false"))
const.ADJUST_TIME = 0 if const.IS_LOCAL else 9


#####################
## for firestore
#####################
if os.environ.get("FIRESTORE_DB_NAME") == "default":
    const.FIRESTORE_DATABASE = "(default)"
else:
    const.FIRESTORE_DATABASE = os.environ.get("FIRESTORE_DB_NAME")

#####################
## for ADK
#####################
os.environ["GOOGLE_CLOUD_PROJECT"] = const.PROJECT_ID
os.environ["GOOGLE_CLOUD_LOCATION"] = const.LOCATION
os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "true"
os.environ["OTEL_SDK_DISABLED"] = "true"

#####################
## for logging
#####################
import logging

formatter = logging.Formatter(
    "[%(asctime)s][%(levelname)s](%(filename)s:%(lineno)s)[pid:%(process)d] %(message)s"
)
stdout_handler = logging.StreamHandler(sys.stdout)
stdout_handler.setFormatter(formatter)

const.LOG_LEVEL = str(os.environ.get("LOG_LEVEL", "WARNING")).upper()
const.logger = logging.getLogger()
const.logger.addHandler(stdout_handler)
const.logger.setLevel(getattr(logging, const.LOG_LEVEL))
