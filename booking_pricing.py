# booking_pricing.py
from typing import Any, Dict, List
import urllib.parse

CAB_RATES = {
    "Include Dedicated Cab (Innova / Scorpio / Bolero 4x4)": 4200,
    "Self-Arranged (No Cab Required)": 0,
}

EXTRA_BED_RATE_PER_NIGHT = 900  # For Per Room properties when heads > rooms * 2

def calculate_dynamic_sheet_quotation(
    matched_stays: List[Dict[str, Any]],
    total_days: int,
    num_heads: int,
    num_rooms: int,
    cab_option: str,
    gst_percent: float = 5.0,
) -> Dict[str, Any]:
    """
    Computes complete trip cost across all nights and days.
    """
    # 1. Guarantee total_days reflects the full list of days
    actual_days = max(len(matched_stays), int(total_days))
    
    # In travel operations, an N-day tour has N-1 hotel nights (e.g., 4 Days = 3 Nights).
    # If it's a 1-day trip, it charges 1 day/night.
    nights = max(1, actual_days - 1) if actual_days > 1 else 1

    # 2. Slice the stays for the exact number of nights
    stays_to_charge = matched_stays[:nights]

    total_hotel_cost = 0.0
    stay_breakdown = []

    for idx, s in enumerate(stays_to_charge):
        night_num = idx + 1
        hotel_name = s.get("stay_name", f"Curated Stay Night {night_num}")
        rate = float(s.get("rate", 1500.0))
        p_type = s.get("pricing_type", "Per Room")
        plan = s.get("plan", "EP")
        plan_desc = s.get("plan_desc", "")

        if p_type == "Per Head":
            night_cost = rate * num_heads
            formula_desc = f"₹{rate:,.0f} × {num_heads} heads ({plan})"
        else:  # Per Room
            base_room_cost = rate * num_rooms
            standard_cap = num_rooms * 2
            extra_heads = max(0, num_heads - standard_cap)
            extra_bed_cost = extra_heads * EXTRA_BED_RATE_PER_NIGHT
            night_cost = base_room_cost + extra_bed_cost

            if extra_heads > 0:
                formula_desc = f"₹{rate:,.0f} × {num_rooms} rooms + ₹{extra_bed_cost:,.0f} ({extra_heads} extra bed) ({plan})"
            else:
                formula_desc = f"₹{rate:,.0f} × {num_rooms} rooms ({plan})"

        total_hotel_cost += night_cost
        stay_breakdown.append({
            "night": night_num,
            "hotel": hotel_name,
            "plan": plan,
            "plan_desc": plan_desc,
            "pricing_type": p_type,
            "rate": rate,
            "cost": night_cost,
            "formula": formula_desc,
        })

    # 3. Sightseeing cab across all tour days
    cab_daily_rate = CAB_RATES.get(cab_option, 0)
    total_cab_cost = cab_daily_rate * actual_days

    # 4. Final Totals
    subtotal = total_hotel_cost + total_cab_cost
    gst_amount = round(subtotal * (gst_percent / 100))
    grand_total = subtotal + gst_amount
    advance_payable = round(grand_total * 0.25)
    per_head = round(grand_total / num_heads) if num_heads > 0 else grand_total

    return {
        "nights": nights,
        "total_days": actual_days,
        "hotel_cost": total_hotel_cost,
        "stay_breakdown": stay_breakdown,
        "cab_cost": total_cab_cost,
        "subtotal": subtotal,
        "gst_amount": gst_amount,
        "grand_total": grand_total,
        "advance_payable": advance_payable,
        "per_head": per_head,
    }

def generate_upi_qr_url(
    vpa: str, payee_name: str, amount: float, booking_id: str
) -> str:
  upi_uri = (
      f"upi://pay?pa={urllib.parse.quote(vpa)}"
      f"&pn={urllib.parse.quote(payee_name)}"
      f"&am={amount:.2f}"
      f"&cu=INR"
      f"&tn={urllib.parse.quote(f'Adv_{booking_id}')}"
  )
  return f"https://quickchart.io/qr?text={urllib.parse.quote(upi_uri)}&size=240&ecLevel=M&margin=1"