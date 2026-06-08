from fastapi import APIRouter, HTTPException, Depends
from fastapi.security.api_key import APIKeyHeader
from database import database
from pydantic import BaseModel, Field
from datetime import date
from typing import Optional
from uuid import UUID

router = APIRouter()

# --- SECURITY ---
API_KEY = "key" 
api_key_header = APIKeyHeader(name="X-API-KEY", auto_error=False)

async def get_api_key(header_key: str = Depends(api_key_header)):
    if header_key == API_KEY:
        return header_key
    raise HTTPException(status_code=404, detail="Unauthorized: Invalid API Key")

# --- SCHEMAS (CONTRACTS) ---

class FarmRecordCreate(BaseModel):
    record_date: Optional[date] = None
    mode_of_record: str  # e.g., "GPS", "Manual", "Sensor"
    record_type: str    # e.g., "Planting", "Harvest", "Land Prep"
    farm_size_hectares: Optional[float] = None
    crop_type: Optional[str] = None

class UserOnboard(BaseModel):
    """Frictionless registration: No National ID allowed yet."""
    fullname: str
    phonenumber: Optional[str] = None
    crops_grown: Optional[str] = None
    farm_location: Optional[str] = None
    primary_goal: Optional[str] = None

class UserUpdate(BaseModel):
    """The 'Verification' stage: Securely adds National ID."""
    national_id: str

class DashboardResponse(BaseModel):
    user_name: str
    user_id: Optional[UUID] = None 
    crops_grown: Optional[str] = None
    years_active: int
    credit_status: str # Will now safely hold 'UNVERIFIED' for non-CRB users
    payment_history_score: Optional[float] = None
    days_past_due: int
    active_loans_count: int

class DenialReason(BaseModel):
    criterion: str       # e.g., "Credit Status", "Credit Score", "Days Past Due"
    current_value: str   # e.g., "DEFAULT", "30.00", "105 days"
    required_value: str  # e.g., "FAIR or better", "60.00+", "Max 15 days"
    message: str         # Helpful text explaining the gap

class RecommendationResponse(BaseModel):
    mfi_name: str
    loan_name: str
    loan_type: str
    max_amount_mkw: float
    why_this_loan: str
    is_qualified: bool = True  # Tells Flutter if this is an offer or a locked product
    denial_reasons: Optional[list[DenialReason]] = None


class LoanApplyRequest(BaseModel):
    loan_name: str
    amount_requested: float

class LoanApplicationResponse(BaseModel):
    application_id: UUID
    loan_name: str
    amount_requested: float
    application_status: str
    status_reason: str
    applied_at: date

# --- API ROUTES ---

@router.post("/onboard")
async def onboard_user(user: UserOnboard):
    """Step 1: Simple registration into the 'users' table."""
    try:
        formatted_name = user.fullname.strip().title()
        
        query = """
            INSERT INTO users (fullname, phonenumber, crops_grown, farm_location, primary_goal)
            VALUES (:fullname, :phonenumber, :crops_grown, :farm_location, :primary_goal)
        """
        values = user.model_dump()
        values["fullname"] = formatted_name 
        await database.execute(query, values=values)
        return {"status": "success", "message": f"User {formatted_name} created."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Registration Failed: {str(e)}")

@router.patch("/user/{identifier}/update", dependencies=[Depends(get_api_key)])
async def update_farmer(identifier: str, data: UserUpdate):
    """
    Step 2: Verification Engine
    Intelligently cross-checks National IDs against CRB records using name/phone fallbacks
    to catch typos and prevent unverified duplication.
    """
    new_id = data.national_id.strip()
    
    try:
        async with database.transaction():
            # 1. Locate the internal user registry profile
            u_query = """
                SELECT user_id, fullname, phonenumber, national_id 
                FROM users 
                WHERE CAST(user_id AS TEXT) = :id 
                OR LOWER(fullname) = LOWER(:id) 
                OR national_id = :id 
                LIMIT 1
            """
            user = await database.fetch_one(u_query, {"id": identifier})
            
            if not user:
                raise HTTPException(status_code=404, detail="User not found")

            target_uuid = user['user_id']
            user_name_clean = user['fullname'].strip().lower()
            user_phone = user['phonenumber'].strip() if user['phonenumber'] else ""

            # 2. Direct Lookup: Does this specific typed National ID exist in the CRB?
            crb_query = "SELECT full_name, phone_number FROM crb_data WHERE national_id = :nid"
            crb_rec = await database.fetch_one(crb_query, {"nid": new_id})

            if crb_rec:
                # Direct match found -> Verify that the identity matches the name on the account
                crb_name_clean = crb_rec['full_name'].strip().lower()
                if crb_name_clean != user_name_clean:
                    raise HTTPException(
                        status_code=400, 
                        detail=f"Identity mismatch: This National ID belongs to {crb_rec['full_name']}."
                    )
                msg = f"Profile verified and linked with CRB records for {user['fullname']}."
            
            else:
                # 3. Typo Protection Engine (No direct ID match found)
                # Check if there is a CRB record matching BOTH the user's name and phone number
                fallback_query = """
                    SELECT national_id, full_name 
                    FROM crb_data 
                    WHERE LOWER(full_name) = :name AND phone_number = :phone
                    LIMIT 1
                """
                suspected_match = await database.fetch_one(fallback_query, {"name": user_name_clean, "phone": user_phone})

                if suspected_match:
                    # Typo detected! The name and phone matched a row, but the user typed a different ID
                    correct_id_hint = suspected_match['national_id']
                    # Mask the ID for privacy security but leave enough to show the typo
                    masked_hint = f"{correct_id_hint[:3]}...{correct_id_hint[-2:]}" if len(correct_id_hint) > 4 else "***"
                    
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            f"Warning: National ID validation failed. We found your profile under a different ID "
                            f"({masked_hint}). Please verify your input characters for typos or poor lighting visibility."
                        )
                    )
                
                # 4. Absolute Fallback: Truly not in the CRB table at all (Save as unverified)
                msg = f"National ID saved for {user['fullname']}. (CRB record not found; credit profile initialized to default)."

            # 5. Securely save verified or fallback ID state
            await database.execute(
                "UPDATE users SET national_id = :nid, last_login = NOW() WHERE user_id = :uid",
                {"nid": new_id, "uid": target_uuid}
            )

            # 6. Initialize tracking points safely
            await database.execute(
                "INSERT INTO points (user_id) VALUES (:uid) ON CONFLICT (user_id) DO NOTHING",
                {"uid": target_uuid}
            )

        return {"status": "success", "message": msg}
    
    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"Error during update processing: {e}")
        raise HTTPException(status_code=500, detail="Internal server error during profile verification verification pipeline")
    
@router.post("/user/{identifier}/farm-records", dependencies=[Depends(get_api_key)])
async def add_farm_record(identifier: str, record: FarmRecordCreate):
    try:
        async with database.transaction():
            u_query = """
                SELECT user_id FROM users 
                WHERE CAST(user_id AS TEXT) = :id 
                OR phonenumber = :id 
                LIMIT 1
            """
            user = await database.fetch_one(u_query, {"id": identifier})
            
            if not user:
                raise HTTPException(status_code=404, detail="User not found")

            r_query = """
                INSERT INTO farm_records (
                    user_id, record_date, mode_of_record, record_type, farm_size_hectares, crop_type
                )
                VALUES (:uid, :rdate, :mode, :rtype, :size, :crop)
                RETURNING record_id
            """
            values = {
                "uid": user['user_id'],
                "rdate": record.record_date or date.today(),
                "mode": record.mode_of_record,
                "rtype": record.record_type,
                "size": record.farm_size_hectares,
                "crop": record.crop_type
            }
            
            record_id = await database.execute(r_query, values=values)

        return {
            "status": "success", 
            "message": "Farm record logged. Trust points updated.",
            "record_id": record_id
        }
    except Exception as e:
        print(f"Error logging farm record: {e}")
        raise HTTPException(status_code=500, detail="Could not save farm record")
    
@router.get("/user/{identifier}/farm-records", dependencies=[Depends(get_api_key)])
async def get_farm_records(identifier: str):
    try:
        u_query = "SELECT user_id FROM users WHERE CAST(user_id AS TEXT) = :id OR phonenumber = :id LIMIT 1"
        user = await database.fetch_one(u_query, {"id": identifier})
        
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        r_query = """
            SELECT record_id, record_date, mode_of_record, record_type, farm_size_hectares, crop_type 
            FROM farm_records 
            WHERE user_id = :uid 
            ORDER BY record_date DESC
        """
        records = await database.fetch_all(r_query, {"uid": user['user_id']})

        return {
            "status": "success",
            "count": len(records),
            "data": records
        }
    except Exception as e:
        print(f"Error fetching records: {e}")
        raise HTTPException(status_code=500, detail="Could not retrieve farm records")

@router.get("/dashboard/{identifier}", response_model=DashboardResponse)
async def get_dashboard(identifier: str):
    """Retrieves aggregated summary metrics including new CRB indicator values."""
    query = """
        SELECT * FROM farmer_status_summary 
        WHERE user_name = :id 
        OR CAST(user_id AS TEXT) = :id 
        LIMIT 1
    """
    try:
        row = await database.fetch_one(query, values={"id": identifier})
        if not row:
            raise HTTPException(status_code=404, detail="Farmer record not found")
        return dict(row)
    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"Dashboard Query Error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error fetching dashboard data")


@router.get("/user/{identifier}/recommendations", response_model=list[RecommendationResponse])
async def get_mfi_recommendations(identifier: str):
    """
    Analyzes credit status metrics and returns eligible loans.
    If the applicant is disqualified from premium products, it breaks down the exact reasons why.
    """
    try:
        # 1. Fetch individual's current CRB health statistics
        profile_query = """
            SELECT credit_status, payment_history_score, days_past_due 
            FROM farmer_status_summary 
            WHERE user_name = :id OR CAST(user_id AS TEXT) = :id 
            LIMIT 1
        """
        farmer = await database.fetch_one(profile_query, {"id": identifier})
        
        if not farmer:
            raise HTTPException(status_code=404, detail="Farmer profile not found to evaluate credit status.")
            
        status = farmer["credit_status"]
        score = float(farmer["payment_history_score"]) if farmer["payment_history_score"] else 0.0
        dpd = farmer["days_past_due"]

        # Map credit ranks to numeric weights for evaluation comparisons
        status_weights = {"UNVERIFIED": 0, "DEFAULT": 1, "BAD": 2, "FAIR": 3, "GOOD": 4, "EXCELLENT": 5}
        user_weight = status_weights.get(status, 0)

        # 2. Grab all active loans in the system to run them through our compliance evaluator
        loans_query = """
            SELECT m.name as mfi_name, l.loan_name, l.loan_type, l.max_amount_mkw, l.why_this_loan, 
                   l.min_credit_status, l.min_payment_history_score, l.max_days_past_due
            FROM mfi_loans l
            JOIN mfis m ON l.mfi_id = m.id
            WHERE m.is_active = true
        """
        all_loans = await database.fetch_all(loans_query)

        recommendations = []
        
        # 3. Evaluate each loan algorithmically
        for loan in all_loans:
            loan_errors = []
            required_weight = status_weights.get(loan["min_credit_status"], 0)

            # Check Condition A: Credit Status Weight
            if user_weight < required_weight:
                loan_errors.append(DenialReason(
                    criterion="Credit Standing Category",
                    current_value=status,
                    required_value=f"{loan['min_credit_status']} or better",
                    message=f"Your profile is marked as {status}. Lenders require a baseline category of {loan['min_credit_status']}."
                ))

            # Check Condition B: Payment History Score (Skip if user is completely unverified)
            if status != "UNVERIFIED" and score < float(loan["min_payment_history_score"]):
                loan_errors.append(DenialReason(
                    criterion="Payment History Rating",
                    current_value=f"{score:.2f}",
                    required_value=f"{float(loan['min_payment_history_score']):.2f}+",
                    message="Your historical payment index score is lower than the threshold required for this financial product."
                ))

            # Check Condition C: Days Past Due (Arrears limits)
            if dpd > loan["max_days_past_due"]:
                loan_errors.append(DenialReason(
                    criterion="Days Past Due Arrears",
                    current_value=f"{dpd} days",
                    required_value=f"Maximum {loan['max_days_past_due']} days",
                    message=f"You currently have repayments outstanding for {dpd} days, exceeding the lender parameter limit of {loan['max_days_past_due']} days."
                ))

            # Assemble response object based on qualification status
            if not loan_errors:
                # User qualifies completely!
                recommendations.append(RecommendationResponse(
                    mfi_name=loan["mfi_name"],
                    loan_name=loan["loan_name"],
                    loan_type=loan["loan_type"],
                    max_amount_mkw=float(loan["max_amount_mkw"]),
                    why_this_loan=loan["why_this_loan"],
                    is_qualified=True,
                    denial_reasons=[]
                ))
            else:
                # User is disqualified, append with explicit feedback
                recommendations.append(RecommendationResponse(
                    mfi_name=loan["mfi_name"],
                    loan_name=loan["loan_name"],
                    loan_type=loan["loan_type"],
                    max_amount_mkw=float(loan["max_amount_mkw"]),
                    why_this_loan=f"This product is locked. Resolve outstanding arrears parameters to open access.",
                    is_qualified=False,
                    denial_reasons=loan_errors
                ))

        return recommendations

    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"Engine recommendation processing error: {e}")
        raise HTTPException(status_code=500, detail="Could not compute conditional loan matrix matches.")
    
@router.post("/user/{identifier}/apply-loan", response_model=LoanApplicationResponse, dependencies=[Depends(get_api_key)])
async def apply_for_loan(identifier: str, payload: LoanApplyRequest):
    """
    Submits a loan application for a farmer.
    The database trigger will instantly calculate the dummy approval outcome.
    """
    try:
        # 1. Identify the internal user
        u_query = """
            SELECT user_id FROM users 
            WHERE CAST(user_id AS TEXT) = :id 
            OR phonenumber = :id 
            LIMIT 1
        """
        user = await database.fetch_one(u_query, {"id": identifier})
        if not user:
            raise HTTPException(status_code=404, detail="User profile not found.")

        # 2. Extract the corresponding MFI linked to this loan product
        mfi_query = "SELECT mfi_id FROM mfi_loans WHERE loan_name = :name LIMIT 1"
        loan_product = await database.fetch_one(mfi_query, {"name": payload.loan_name})
        if not loan_product:
            raise HTTPException(status_code=404, detail="Selected loan product does not exist.")

        # 3. Insert the application row into the database (Triggers auto-evaluation)
        insert_query = """
            INSERT INTO loan_applications (user_id, mfi_id, loan_name, amount_requested)
            VALUES (:uid, :mfi_id, :loan_name, :amount)
            RETURNING id, loan_name, amount_requested, application_status, status_reason, applied_at::date
        """
        values = {
            "uid": user["user_id"],
            "mfi_id": loan_product["mfi_id"],
            "loan_name": payload.loan_name,
            "amount": payload.amount_requested
        }
        
        result = await database.fetch_one(insert_query, values=values)
        
        return LoanApplicationResponse(
            application_id=result["id"],
            loan_name=result["loan_name"],
            amount_requested=float(result["amount_requested"]),
            application_status=result["application_status"],
            status_reason=result["status_reason"],
            applied_at=result["applied_at"]
        )

    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"Loan submission application error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error processing loan submission.")


@router.get("/user/{identifier}/loans", response_model=list[LoanApplicationResponse], dependencies=[Depends(get_api_key)])
async def get_loan_history(identifier: str):
    """
    Returns a list of all historical loan requests submitted by the individual.
    """
    try:
        # 1. Identify user
        u_query = "SELECT user_id FROM users WHERE CAST(user_id AS TEXT) = :id OR phonenumber = :id LIMIT 1"
        user = await database.fetch_one(u_query, {"id": identifier})
        if not user:
            raise HTTPException(status_code=404, detail="User profile not found.")

        # 2. Fetch history ordered by newest first
        history_query = """
            SELECT id as application_id, loan_name, amount_requested, application_status, status_reason, applied_at::date
            FROM loan_applications
            WHERE user_id = :uid
            ORDER BY applied_at DESC
        """
        rows = await database.fetch_all(history_query, {"uid": user["user_id"]})
        
        return [
            {
                "application_id": r["application_id"],
                "loan_name": r["loan_name"],
                "amount_requested": float(r["amount_requested"]),
                "application_status": r["application_status"],
                "status_reason": r["status_reason"],
                "applied_at": r["applied_at"]
            }
            for r in rows
        ]
    except Exception as e:
        print(f"Error fetching loan history: {e}")
        raise HTTPException(status_code=500, detail="Could not retrieve loan applications history.")