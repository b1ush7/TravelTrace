from app.db.models import Claim
from app.modules.claims.schemas import ClaimOut, ClaimValue


def claim_out(claim: Claim) -> ClaimOut:
    return ClaimOut(
        id=claim.id,
        subject_member_id=claim.subject_member_id,
        speaker_member_id=claim.speaker_member_id,
        field=claim.field,
        value=ClaimValue.model_validate(claim.value),
        condition=claim.condition,
        polarity=claim.polarity,
        strength=claim.strength,
        status=claim.status,
        source_message_id=claim.source_message_id,
        version=claim.version,
    )


def claim_value_dict(value: ClaimValue) -> dict:
    return value.model_dump(mode="json", exclude_none=True)
