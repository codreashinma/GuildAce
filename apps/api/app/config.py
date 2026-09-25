from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """環境変数（.env）から読む設定。未設定の外部連携はモックで動く。"""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- app ---
    database_url: str = "postgresql+psycopg://choice:choice@localhost:5433/choice"
    jwt_secret: str = "dev-secret-change-me"
    cors_origins: str = "http://localhost:3000"
    app_url: str = "http://localhost:3000"
    api_url: str = "http://localhost:8001"
    dev_login_enabled: bool = False  # true で /auth/dev-login（ウォレット不要のデモログイン）を有効化

    # --- chain (Sepolia) ---
    chain_id: int = 11155111
    sepolia_rpc_url: str = ""
    server_private_key: str = ""  # 運用ウォレット（ops）: Escrow の中継、ENS の所有者としての発行・プロフィール更新
    reputation_private_key: str = ""  # EAC: codrea.agent.rating/reviews/completed の setText だけを許された鍵
    project_private_key: str = ""  # EAC: Agent サブレジストリへの register と codrea.project.* の setText だけを許された鍵
    escrow_address: str = ""
    usdc_address: str = ""

    # --- ENS (ENSv2 Sepolia beta) ---
    ens_parent_name: str = "choice.eth"
    ens_write_enabled: bool = False
    ens_universal_resolver: str = "0xeEeEEEeE14D718C2B47D9923Deab1335E144EeEe"
    ensv2_eth_registry: str = "0xBDC85dD5b15D7ecb354cd7cb6f2c50b4f2c4F0E2"
    ensv2_registrar: str = "0xa88553F454b77203B0D036A05c894d555EAAa2Cc"
    ensv2_payment_token: str = "0x768F42455A2D082E23ceeF7d51e5787C82d67a39"
    ensv2_verifiable_factory: str = "0x10dC6333CDFe1FCEf624c6e0a8221b91804Cd7ef"
    ensv2_resolver_impl: str = "0x9EAe5C2730a7dD16BDD1DeE6421a1B91e3B0365e"
    ensv2_subregistry_impl: str = "0x624a25d67B59D587752EbEc8DdeD8827dAe52050"
    ens_owned_resolver: str = ""  # scripts/ens_setup.py が出力
    ens_parent_subregistry: str = ""  # scripts/ens_setup.py が出力
    ens_reputation_resolver: str = ""  # Reputation 鍵が admin の PermissionedResolver（reputation.<agent> 用）
    ens_project_resolver: str = ""  # Project 鍵が admin の PermissionedResolver（project-*.<agent> 用）

    # --- World ID ---
    world_app_id: str = ""
    world_rp_id: str = ""
    world_rp_signing_key: str = ""
    world_verify_enabled: bool = False
    world_verify_url: str = "https://developer.world.org/api/v4/verify"

    # --- Gemini ---
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def chain_enabled(self) -> bool:
        return bool(self.sepolia_rpc_url and self.escrow_address and self.usdc_address)

    @property
    def gemini_enabled(self) -> bool:
        return bool(self.gemini_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
