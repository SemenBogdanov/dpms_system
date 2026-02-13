import type { ShopItem } from '@/api/types'
import { QBadge } from './QBadge'

interface ShopCardProps {
  item: ShopItem
  /** Сколько раз пользователь уже купил этот товар в текущем месяце */
  purchasedThisMonth: number
  /** Баланс кармы пользователя */
  karmaBalance: number
  onPurchase: (item: ShopItem) => void
}

/** Карточка товара в магазине. */
export function ShopCard({
  item,
  purchasedThisMonth,
  karmaBalance,
  onPurchase,
}: ShopCardProps) {
  const canBuy = item.is_active && karmaBalance >= item.cost_q && purchasedThisMonth < item.max_per_month
  const limitReached = purchasedThisMonth >= item.max_per_month
  const notEnoughKarma = karmaBalance < item.cost_q
  const needMore = notEnoughKarma ? (item.cost_q - karmaBalance).toFixed(1) : null

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm flex flex-col">
      <div className="text-4xl mb-2">{item.icon}</div>
      <h3 className="font-semibold text-slate-900">{item.name}</h3>
      <p className="mt-1 text-sm text-slate-500 line-clamp-2">{item.description}</p>
      <div className="mt-3 flex items-center gap-2">
        <QBadge q={item.cost_q} />
        <span className="text-xs text-slate-500">
          Осталось: {purchasedThisMonth}/{item.max_per_month} в этом месяце
        </span>
      </div>
      <div className="mt-4 flex-1 flex items-end">
        <button
          type="button"
          disabled={!canBuy}
          title={
            limitReached
              ? 'Лимит исчерпан в этом месяце'
              : notEnoughKarma && needMore
                ? `Нужно ещё ${needMore} Q`
                : undefined
          }
          onClick={() => canBuy && onPurchase(item)}
          className="w-full rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          Купить
        </button>
      </div>
    </div>
  )
}
