
import aiorexense.const as const

def test_constants():
    assert const.DEFAULT_PORT == 80
    assert const.API_VERSION == "1.0"
    assert const.VENDOR_CODE == "Rexense"
    assert const.FUNCTION_GET_BASIC_INFO == "GetBasicInfo"
    assert isinstance(const.REXENSE_SENSOR_CURRENT, dict)
    # test some sensor fields
    assert const.REXENSE_SENSOR_CURRENT["name"] == "Current"
    assert const.REXENSE_SENSOR_TEMPERATURE["unit"] == "°C"
    assert const.REXENSE_SWITCH_ONOFF["name"] == "PowerSwitch"
