"""Constants for the BMW CE-02 Charge Tracker integration."""

DOMAIN = "bmw_ce02_charge_tracker"

# Configuration keys
CONF_DEVICE_NAME = "device_name"
CONF_POWER_SENSOR_ENTITY_ID = "power_sensor_entity_id"
CONF_MIN_CHARGING_POWER = "min_charging_power"

# Default values
DEFAULT_NAME = "BMW CE-02"
DEFAULT_MIN_CHARGING_POWER_W = 10.0 # Watts

# Battery parameters (CHARGER_POWER)
BATTERY_CAPACITY_KWH = 3.92
# SOC_THRESHOLD_PHASE2 is still used for *estimating* time to 80%
SOC_THRESHOLD_PHASE2 = 80 # Limite de l'état de charge pour la phase 2
CHARGER_LOST_FACTOR = 0.92 # Perte de charge du chargeur

# Update interval for SoC calculation when charging
UPDATE_INTERVAL_CHARGING_SECONDS = 60

# States for time remaining sensors
TIME_REMAINING_STATUS_REACHED = "Atteint"
TIME_REMAINING_STATUS_FULL = "Pleine"
TIME_REMAINING_STATUS_UNAVAILABLE = "Indisponible"