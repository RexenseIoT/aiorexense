"""
Rexense const & sensor config
"""

DEFAULT_PORT = 80

API_VERSION = "1.0"
VENDOR_CODE = "Rexense"
FUNCTION_GET_BASIC_INFO = "GetBasicInfo"
FUNCTION_NOTIFY_STATUS = "NotifyStatus"
FUNCTION_INVOKE_CMD = "InvokeCmd"

REXENSE_SENSOR_CURRENT = {"name":"Current","unit":"A"}
REXENSE_SENSOR_VOLTAGE = {"name":"Voltage","unit":"V"}
REXENSE_SENSOR_POWER_FACTOR = {"name":"PowerFactor","unit":""}
REXENSE_SENSOR_ACTIVE_POWER = {"name":"ActivePower","unit":"W"}
REXENSE_SENSOR_APPARENT_POWER = {"name":"AprtPower","unit":"VA"}
REXENSE_SENSOR_B_CURRENT = {"name":"B_Current","unit":"A"}
REXENSE_SENSOR_B_VOLTAGE = {"name":"B_Voltage","unit":"V"}
REXENSE_SENSOR_B_POWER_FACTOR = {"name":"B_PowerFactor","unit":""}
REXENSE_SENSOR_B_ACTIVE_POWER = {"name":"B_ActivePower","unit":"W"}
REXENSE_SENSOR_B_APPARENT_POWER = {"name":"B_AprtPower","unit":"VA"}
REXENSE_SENSOR_C_CURRENT = {"name":"C_Current","unit":"A"}
REXENSE_SENSOR_C_VOLTAGE = {"name":"C_Voltage","unit":"V"}
REXENSE_SENSOR_C_POWER_FACTOR = {"name":"C_PowerFactor","unit":""}
REXENSE_SENSOR_C_ACTIVE_POWER = {"name":"C_ActivePower","unit":"W"}
REXENSE_SENSOR_C_APPARENT_POWER = {"name":"C_AprtPower","unit":"VA"}
REXENSE_SENSOR_TOTAL_ACTIVE_POWER = {"name":"TotalActivePower","unit":"W"}
REXENSE_SENSOR_TOTAL_APPARENT_POWER = {"name":"TotalAprtPower","unit":"VA"}
REXENSE_SENSOR_CEI = {"name":"CEI","unit":"kWh"}
REXENSE_SENSOR_CEE = {"name":"CEE","unit":"kWh"}
REXENSE_SENSOR_A_CEI = {"name":"A_CEI","unit":"kWh"}
REXENSE_SENSOR_A_CEE = {"name":"A_CEE","unit":"kWh"}
REXENSE_SENSOR_B_CEI = {"name":"B_CEI","unit":"kWh"}
REXENSE_SENSOR_B_CEE = {"name":"B_CEE","unit":"kWh"}
REXENSE_SENSOR_C_CEI = {"name":"C_CEI","unit":"kWh"}
REXENSE_SENSOR_C_CEE = {"name":"C_CEE","unit":"kWh"}
REXENSE_SENSOR_TEMPERATURE = {"name":"Temperature","unit":"°C"}
REXENSE_SENSOR_BATTERY_PERCENTAGE = {"name":"BatteryPercentage","unit":"%"}
REXENSE_SENSOR_BATTERY_VOLTAGE = {"name":"BatteryVoltage","unit":"V"}

REXENSE_SWITCH_ONOFF = {"name":"PowerSwitch","unit":""}
