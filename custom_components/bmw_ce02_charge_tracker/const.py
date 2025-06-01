DOMAIN = "bmw_ce02_charge_tracker"

# Configuration keys
CONF_DEVICE_NAME = "device_name"

# Default values
DEFAULT_NAME = "BMW CE-02"

# Charging parameters
CHARGER_POWER_PHASE1_KW = 0.9  # Puissance pour 0-89% SoC
CHARGER_POWER_PHASE2_KW = 0.517 # Puissance pour 89-100% SoC
BATTERY_CAPACITY_KWH = 3.92
SOC_THRESHOLD_PHASE2 = 89 # Pourcentage SoC où la puissance de charge change

# Update interval for SoC calculation when charging
UPDATE_INTERVAL_CHARGING_SECONDS = 60