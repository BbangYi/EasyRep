"""Sensitivity calculation for an unoccupied 20 x 20 x 30 cm prototype.

These are declared engineering assumptions, not measurements or husbandry limits.
Run: python3 docs/hardware-design/thermal-sizing.py
"""
import json
import math

VOLUME_M3 = 0.2 * 0.2 * 0.3
AREA_M2 = 2 * (0.2 * 0.2 + 0.2 * 0.3 + 0.2 * 0.3)
RHO_CP = 1200  # J/(m3 K), approximate volumetric heat capacity of room air
LATENT_J_G = 2440  # approximate at room temperature


def load(delta_k, mode):
    bounds = []
    for u, ach, moisture_g_h, internal_w, idle_bridge_w in (
        (3, 10, 1, 1, 2), (6, 60, 5, 2, 5)
    ):
        wall = u * AREA_M2 * delta_k
        ventilation = RHO_CP * VOLUME_M3 * ach / 3600 * delta_k
        moisture = moisture_g_h * LATENT_J_G / 3600
        # Cooling: condensation load. Heating: evaporation load.
        # Heating neglects helpful fan heat and includes an idle TEC heat bridge.
        extra = internal_w if mode == "cooling" else idle_bridge_w
        total = wall + ventilation + moisture + extra
        bounds.append({
            "wall_w": round(wall, 2),
            "ventilation_w": round(ventilation, 2),
            "moisture_w": round(moisture, 2),
            "other_w": extra,
            "total_w": round(total, 2),
            "with_30_percent_margin_w": round(total * 1.3, 2),
        })
    return bounds


def dewpoint(t, rh):
    gamma = math.log(rh / 100) + 17.62 * t / (243.12 + t)
    return round(243.12 * gamma / (17.62 - gamma), 1)


if __name__ == "__main__":
    print(json.dumps({
        "status": "assumption_based_sensitivity_not_measured",
        "gross_volume_l": round(VOLUME_M3 * 1000, 2),
        "envelope_area_m2": round(AREA_M2, 3),
        "assumptions": {
            "effective_u_w_m2_k": [3, 6],
            "external_air_changes_per_hour": [10, 60],
            "moisture_change_g_h": [1, 5],
            "solar_load": "excluded; no direct sunlight",
            "door_opening": "excluded from steady state",
            "insulation_benefit": "not credited",
        },
        "summer_32_to_26_c": load(6, "cooling"),
        "summer_stress_35_to_26_c": load(9, "cooling"),
        "winter_18_to_24_c": load(6, "heating"),
        "winter_stress_10_to_24_c": load(14, "heating"),
        "dewpoint_at_26_c": {str(rh): dewpoint(26, rh) for rh in (60, 70, 80, 90)},
        "recirculation_for_20_w_at_5_k_l_min": round(20 / (RHO_CP * 5) * 60000),
        "recirculation_for_25_w_at_5_k_l_min": round(25 / (RHO_CP * 5) * 60000),
        "hot_side_example": {
            "qc_w": 25, "tec_input_w": 50, "qh_w": 75,
            "room_c": 32, "target_hot_c": 45,
            "total_hot_side_thermal_resistance_k_w": round((45 - 32) / 75, 3),
        },
        "thermal_supply_budget": {
            "tec_driver_input_cap_w": 60, "heater_cap_w": 30,
            "fans_w": 5, "logic_and_conversion_w": 6,
            "normal_cooling_w": 71, "normal_heating_w": 41,
            "both_outputs_fault_case_w": 101,
            "reference_supply_w": 102,
            "note": "Simultaneous heating/cooling requires a hardware interlock; 101 W has no design margin.",
        },
    }, ensure_ascii=False, indent=2))
