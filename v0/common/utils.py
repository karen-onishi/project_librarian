from datetime import datetime, timedelta, timezone


def convert_utc_to_jst(utc_timestamp: str | datetime) -> str:
    from common.const import ADJUST_TIME

    formatted_jst_timestamp = None
    if isinstance(utc_timestamp, str):
        utc_timestamp = datetime.fromisoformat(utc_timestamp.replace("Z", "+00:00"))
        jst = timezone(timedelta(hours=ADJUST_TIME))
        jst_timestamp = utc_timestamp.astimezone(jst)
        jst_timestamp = jst_timestamp.replace(tzinfo=None)
        formatted_jst_timestamp = jst_timestamp.strftime("%Y-%m-%d %H:%M:%S")
    else:
        formatted_jst_timestamp = utc_timestamp.astimezone(
            timezone(timedelta(hours=ADJUST_TIME))
        )

    return formatted_jst_timestamp


def strtobool(val: str) -> bool:
    """Convert a string representation of truth to true (1) or false (0).

    True values are 'y', 'yes', 't', 'true', 'on', and '1'; false values
    are 'n', 'no', 'f', 'false', 'off', and '0'.  Raises ValueError if
    'val' is anything else.
    """
    _lower_val = val.lower()
    if _lower_val in ("y", "yes", "t", "true", "on", "1"):
        return 1
    elif _lower_val in ("n", "no", "f", "false", "off", "0"):
        return 0
    else:
        raise ValueError("invalid truth value {!r}".format(_lower_val))
