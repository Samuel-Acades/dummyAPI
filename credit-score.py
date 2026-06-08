from datetime import datetime
from typing import Optional
from pydantic import BaseModel

class RawCreditDataInput(BaseModel):
    """
    DATA CONTRACT: Your teammate must map their database query fields 
    into this exact object structure before calling your function.
    """
    days_past_due: int
    has_defaults: bool
    credit_utilization: float        # e.g., 22.5 for 22.5%
    debt_to_income_ratio: float      # e.g., 40.0 for 40.0%
    credit_history_months: int
    active_loans_count: int
    successful_repayments_count: int  # Traditional alternative tracking metric
    savings_balance_mkw: float       # Traditional alternative tracking metric


class CreditEngineOutput(BaseModel):
    """
    OUTPUT CONTRACT: The structured analytics your algorithm returns
    to your teammate so they can easily pass it to the Flutter UI.
    """
    credit_score: int
    credit_tier: str                 # EXCELLENT, GOOD, FAIR, POOR, VERY POOR, UNVERIFIED
    risk_assessment: str
    payment_history_grade: float     # Performance metric out of 100
    utilization_grade: float         # Performance metric out of 100
    history_length_grade: float      # Performance metric out of 100
    financial_capacity_grade: float  # Performance metric out of 100
    generated_at: str


def evaluate_farmer_risk(data: Optional[RawCreditDataInput]) -> CreditEngineOutput:
    """
    The Core Scoring Engine Framework.
    Ingests raw risk parameters and processes them through a 300-850 mathematical matrix.
    """
    MIN_SCORE = 300
    MAX_SCORE = 850
    SCORE_RANGE = MAX_SCORE - MIN_SCORE  # 550 total points available

    # 1. Guard Check: Handle completely unverified/new users safely
    if data is None:
        return CreditEngineOutput(
            credit_score=300,
            credit_tier="UNVERIFIED",
            risk_assessment="Unknown Risk: No historical credit or financial registry profile found.",
            payment_history_grade=0.0,
            utilization_grade=0.0,
            history_length_grade=0.0,
            financial_capacity_grade=0.0,
            generated_at=datetime.utcnow().isoformat()
        )

    # ---- FACTOR 1: PAYMENT HISTORY (35% Weight | Max 192.5 Points) ----
    pay_history_base = 100.0
    if data.has_defaults:
        pay_history_base -= 55.0
    if data.days_past_due > 90:
        pay_history_base -= 40.0
    elif data.days_past_due > 30:
        pay_history_base -= 20.0
    elif data.days_past_due > 0:
        pay_history_base -= 10.0
        
    # Traditional alternative data reward bonus points
    if data.successful_repayments_count >= 12:
        pay_history_base += 10.0
        
    payment_history_grade = max(0.0, min(100.0, pay_history_base))
    weighted_payment_points = (payment_history_grade / 100.0) * (SCORE_RANGE * 0.35)


    # ---- FACTOR 2: LIABILITIES & UTILIZATION (30% Weight | Max 165 Points) ----
    util_base = 100.0
    if data.credit_utilization <= 15.0:
        util_base = 100.0
    elif data.credit_utilization <= 30.0:
        util_base = 90.0
    elif data.credit_utilization <= 50.0:
        util_base = 70.0
    elif data.credit_utilization <= 75.0:
        util_base = 35.0
    else:
        util_base = 10.0
        
    utilization_grade = max(0.0, min(100.0, util_base))
    weighted_util_points = (utilization_grade / 100.0) * (SCORE_RANGE * 0.30)


    # ---- FACTOR 3: HISTORY DURATION TIMELINE (15% Weight | Max 82.5 Points) ----
    history_base = 0.0
    if data.credit_history_months >= 48:
        history_base = 100.0
    elif data.credit_history_months >= 24:
        history_base = 85.0
    elif data.credit_history_months >= 12:
        history_base = 55.0
    else:
        history_base = 25.0
        
    history_length_grade = max(0.0, min(100.0, history_base))
    weighted_history_points = (history_length_grade / 100.0) * (SCORE_RANGE * 0.15)


    # ---- FACTOR 4: FINANCIAL CAPACITY MATRIX (20% Weight | Max 110 Points) ----
    capacity_base = 100.0
    if data.debt_to_income_ratio > 50.0:
        capacity_base -= 50.0
    elif data.debt_to_income_ratio > 35.0:
        capacity_base -= 25.0
        
    # Traditional cushion balance reward (e.g., healthy savings buffers)
    if data.savings_balance_mkw >= 150000.0:
        capacity_base += 15.0
        
    financial_capacity_grade = max(0.0, min(100.0, capacity_base))
    weighted_capacity_points = (financial_capacity_grade / 100.0) * (SCORE_RANGE * 0.20)


    # ---- MATRIX SUMMATION & TIER CLASSIFICATION ----
    final_score = int(MIN_SCORE + weighted_payment_points + weighted_util_points + weighted_history_points + weighted_capacity_points)
    final_score = max(MIN_SCORE, min(MAX_SCORE, final_score))

    if final_score >= 740:
        tier, risk = "EXCELLENT", "Minimal Risk: Strong baseline indicator profiles."
    elif final_score >= 670:
        tier, risk = "GOOD", "Low Risk: Sustainable credit performance tracks."
    elif final_score >= 580:
        tier, risk = "FAIR", "Moderate Risk: Acceptable transaction behaviors."
    elif final_score >= 500:
        tier, risk = "POOR", "High Risk: Consistent payment delay trends noted."
    else:
        tier, risk = "VERY POOR", "Critical Risk: Active default profile markers observed."

    return CreditEngineOutput(
        credit_score=final_score,
        credit_tier=tier,
        risk_assessment=risk,
        payment_history_grade=round(payment_history_grade, 1),
        utilization_grade=round(utilization_grade, 1),
        history_length_grade=round(history_length_grade, 1),
        financial_capacity_grade=round(financial_capacity_grade, 1),
        generated_at=datetime.utcnow().isoformat()
    )

# ========================================================
# EXAMPLE RUN WITH SAMPLE SUPABASE DICTIONARY DATA
# ========================================================
if __name__ == "__main__":
    
    # Mock data structure fetched from your Supabase tables
    sample_supabase_payload = {
        'days_past_due': 60,   
        'has_defaults': False,  # Note: Changed from string "False" to actual boolean False
        'credit_utilization': 90.0,  
        'debt_to_income_ratio': 58.0,   
        'credit_history_months': 10,  # Changed to int to match Pydantic schema
        'active_loans_count': 2,  
        'successful_repayments_count': 15,  
        'savings_balance_mkw': 200000.0  
    }
    
    # --- THE FIX: Convert the raw dict into the Pydantic Object ---
    validated_payload = RawCreditDataInput(**sample_supabase_payload)
    
    # Pass the object into your engine
    calculated_score = evaluate_farmer_risk(validated_payload)
    
    print(f"Computed ACADES Credit Score: {calculated_score}")
