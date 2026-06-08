from datetime import datetime
from typing import Optional
from pydantic import BaseModel
save_to_jsonl = lambda data, filename: open(filename, "a").write(str(data) + "\n")

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
    Algorithmic Credit Scoring Engine modeled explicitly as a 
    Weighted Linear Combination (Linear Regression Formula Matrix).
    """
    # 1. Base Parameters (Beta Note Intercept and Available Point Range)
    BETA_0 = 300       # Minimum possible score
    SCORE_RANGE = 550  # Maximum additional points available (850 - 300)

    if data is None:
        return CreditEngineOutput(
            credit_score=BETA_0, tier="UNVERIFIED", risk_assessment="Missing registry profile.",
            payment_history_grade=0.0, utilization_grade=0.0, history_length_grade=0.0,
            financial_capacity_grade=0.0, verification_assets_grade=0.0, generated_at=datetime.utcnow().isoformat()
        )

    # -----------------------------------------------------------------
    # CATEGORY GRADING BLOCKS (Outputs a performance grade from 0 to 100)
    # -----------------------------------------------------------------

    # C1: Payment History Performance Grade
    pay_history_base = 100.0
    if data.has_defaults: pay_history_base -= 55.0
    if data.days_past_due > 90: pay_history_base -= 40.0
    elif data.days_past_due > 30: pay_history_base -= 20.0
    elif data.days_past_due > 0: pay_history_base -= 10.0
    if data.successful_repayments_count >= 12: pay_history_base += 10.0
    C1 = max(0.0, min(100.0, pay_history_base))

    # C2: Credit Utilization Performance Grade
    util_base = 100.0
    if data.credit_utilization <= 15.0: util_base = 100.0
    elif data.credit_utilization <= 30.0: util_base = 90.0
    elif data.credit_utilization <= 50.0: util_base = 70.0
    elif data.credit_utilization <= 75.0: util_base = 35.0
    else: util_base = 10.0
    C2 = max(0.0, min(100.0, util_base))

    # C3: Timeline Duration Performance Grade
    history_base = 0.0
    if data.credit_history_months >= 48: history_base = 100.0
    elif data.credit_history_months >= 24: history_base = 85.0
    elif data.credit_history_months >= 12: history_base = 55.0
    else: history_base = 25.0
    C3 = max(0.0, min(100.0, history_base))

    # C4: Financial Capacity Performance Grade
    capacity_base = 100.0
    if data.debt_to_income_ratio > 50.0: capacity_base -= 50.0
    elif data.debt_to_income_ratio > 35.0: capacity_base -= 25.0
    if data.savings_balance_mkw >= 150000.0: capacity_base += 15.0
    C4 = max(0.0, min(100.0, capacity_base))

    # # C5: Alternative Verification Performance Grade
    # verification_base = 0.0
    # verification_base += data.national_id_points
    # verification_base += data.verify_land_points
    # verification_base += data.link_mobile_numbers_points
    # verification_base += data.trainings_points
    # C5 = max(0.0, min(100.0, verification_base))

    # -----------------------------------------------------------------
    # THE LINEAR REGRESSION WEIGHT EQUATION
    # -----------------------------------------------------------------
    # Defining our structural beta weights explicitly (Must add up to 1.0)
    W1 = 0.40  # Payment History Weight
    W2 = 0.30  # Utilization Weight
    W3 = 0.15  # Length of History Weight
    W4 = 0.15  # Capacity Weight
    # W5 = 0.15  # Alternative Verification Weight

    # The actual regression formula execution
    # We divide C_n by 100 to change the 0-100 grade into a decimal percentage decimal
    total_weighted_percentage = (W1 * (C1 / 100.0)) + \
                                (W2 * (C2 / 100.0)) + \
                                (W3 * (C3 / 100.0)) + \
                                (W4 * (C4 / 100.0)) 
                                # (W5 * (C5 / 100.0))

    # Calculate final credit score
    final_score = int(BETA_0 + (total_weighted_percentage * SCORE_RANGE))
    
    # Boundary capping safety guards
    final_score = max(BETA_0, min(850, final_score))

    # -----------------------------------------------------------------
    # TIER SEGMENTATION LOGIC
    # -----------------------------------------------------------------
    if final_score >= 740: tier, risk = "EXCELLENT", "Minimal Risk Profile"
    elif final_score >= 670: tier, risk = "GOOD", "Low Risk Level"
    elif final_score >= 580: tier, risk = "FAIR", "Moderate Risk Parameters"
    elif final_score >= 500: tier, risk = "POOR", "High Volatility Risk"
    else: tier, risk = "VERY POOR", "Critical Default Risk"

    return CreditEngineOutput(
        credit_score=final_score, credit_tier=tier, risk_assessment=risk,
        payment_history_grade=round(C1, 1), utilization_grade=round(C2, 1),
        history_length_grade=round(C3, 1), financial_capacity_grade=round(C4, 1),
        # verification_assets_grade=round(C5, 1),
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
    save_to_jsonl(calculated_score.dict(), "calculated_score_output.jsonl")
    
    print(f"Computed ACADES Credit Score: {calculated_score}")
