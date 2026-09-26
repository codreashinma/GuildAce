from fastapi import APIRouter

from ..config import get_settings
from ..schemas import ConfigOut
from ..services import ens

router = APIRouter(tags=["config"])


@router.get("/config", response_model=ConfigOut)
def config():
    s = get_settings()
    roles = ens.role_separation()
    return ConfigOut(
        chain_id=s.chain_id,
        escrow_address=s.escrow_address,
        usdc_address=s.usdc_address,
        ens_parent_name=s.ens_parent_name,
        ens_universal_resolver=s.ens_universal_resolver,
        world_app_id=s.world_app_id,
        world_rp_id=s.world_rp_id,
        ens_roles=roles,
        mock={
            "chain": not s.chain_enabled,
            "ens_write": not s.ens_write_enabled,
            # 役割鍵が未設定で Owner 鍵にフォールバックしている = EAC の役割分離が効いていない
            "ens_roles": not roles["separated"],
            "world": not s.world_verify_enabled,
            "gemini": not s.gemini_enabled,
        },
    )
