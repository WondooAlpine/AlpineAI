# coupon_manager.py
import json
import os
from typing import Dict, Any, Tuple

COUPONS_FILE = os.path.join(os.path.dirname(__file__), "coupons.json")

def load_coupons() -> Dict[str, Any]:
    """Loads coupons from the local coupons.json file."""
    if not os.path.exists(COUPONS_FILE):
        return {}
    try:
        with open(COUPONS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading coupons.json: {e}")
        return {}

def save_coupons(coupons_data: Dict[str, Any]) -> bool:
    """Saves updated coupon metadata to coupons.json."""
    try:
        with open(COUPONS_FILE, "w", encoding="utf-8") as f:
            json.dump(coupons_data, f, indent=2)
        return True
    except Exception as e:
        print(f"Error saving coupons.json: {e}")
        return False

def validate_coupon_for_user(code: str, grand_total: float, user_email: str) -> Tuple[bool, str, float]:
    """
    Validates a coupon against:
    1. Existence
    2. Global maximum usage limit (max_uses_global)
    3. One-time per user restriction (is_one_time_per_user)
    4. Minimum booking order threshold (min_order)
    
    Returns: (is_valid, message, discount_amount)
    """
    code_clean = code.strip().upper()
    if not code_clean:
        return False, "Please provide a valid coupon code.", 0.0

    coupons = load_coupons()
    if code_clean not in coupons:
        return False, f"Coupon code '{code_clean}' does not exist.", 0.0

    coupon = coupons[code_clean]
    user_email_clean = user_email.strip().lower()

    # 1. Check Global Usage Limit
    max_global = coupon.get("max_uses_global")
    used_count = coupon.get("used_count", 0)
    if max_global is not None and used_count >= max_global:
        return False, f"Coupon '{code_clean}' has reached its maximum redemptions limit.", 0.0

    # 2. Check One-time Per User Rule
    used_by = [u.lower() for u in coupon.get("used_by_users", [])]
    is_one_time = coupon.get("is_one_time_per_user", False)
    if is_one_time and user_email_clean in used_by:
        return False, f"You have already redeemed '{code_clean}'. This code can only be used once per account.", 0.0

    # 3. Minimum Order Threshold
    min_order = coupon.get("min_order", 0)
    if grand_total < min_order:
        return False, f"Booking total must be at least ₹{min_order:,} to use coupon '{code_clean}'.", 0.0

    # 4. Compute Discount
    c_type = coupon.get("type", "flat")
    c_val = float(coupon.get("value", 0))
    max_disc = float(coupon.get("max_discount", c_val))

    if c_type == "percent":
        discount = (grand_total * c_val) / 100.0
        discount = min(discount, max_disc)
    else:
        discount = min(c_val, max_disc)

    # Ensure discount does not exceed bill amount
    discount = min(discount, grand_total)

    return True, f"Coupon '{code_clean}' applied! You save ₹{discount:,.0f}.", discount


def record_coupon_redemption(code: str, user_email: str) -> bool:
    """
    Increments used_count and appends the user_email to used_by_users in coupons.json.
    Called only when the booking button is confirmed.
    """
    code_clean = code.strip().upper()
    coupons = load_coupons()
    if code_clean not in coupons:
        return False

    coupon = coupons[code_clean]
    coupon["used_count"] = coupon.get("used_count", 0) + 1

    used_by = coupon.get("used_by_users", [])
    user_email_clean = user_email.strip().lower()
    if user_email_clean not in [u.lower() for u in used_by]:
        used_by.append(user_email_clean)
    coupon["used_by_users"] = used_by

    return save_coupons(coupons)