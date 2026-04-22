from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.merchant import Merchant


class MerchantRepository:
    async def get_by_merchant_id(
        self, db: AsyncSession, merchant_id: str
    ) -> Merchant | None:
        result = await db.execute(
            select(Merchant).where(Merchant.merchant_id == merchant_id)
        )
        return result.scalar_one_or_none()

    async def get_or_create(
        self, db: AsyncSession, merchant_id: str, name: str
    ) -> Merchant:
        merchant = await self.get_by_merchant_id(db, merchant_id)
        if merchant:
            return merchant

        merchant = Merchant(merchant_id=merchant_id, name=name)
        db.add(merchant)
        await db.flush()
        return merchant


merchant_repo = MerchantRepository()
