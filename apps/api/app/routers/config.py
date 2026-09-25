from fastapi import APIRouter

from ..config import get_settings
from ..schemas import ConfigOut

router = APIRouter(tags=["config"])


@router.get("/config", response_model=ConfigOut)
def config():
    s = get_settings()
    return ConfigOut(
        chain_id=s.chain_id,
        escrow_address=s.escrow_address,
        usdc_address=s.usdc_address,
        ens_parent_name=s.ens_parent_name,
        ens_universal_resolver=s.ens_universal_resolver,
        world_app_id=s.world_app_id,
        world_rp_id=s.world_rp_id,
        mock={
            "chain": not s.chain_enabled,
            "ens_write": not s.ens_write_enabled,
            "world": not s.world_verify_enabled,
            "gemini": not s.gemini_enabled,
        },
    )
