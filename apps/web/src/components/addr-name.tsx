"use client";
import { useQuery } from "@tanstack/react-query";
import { api, short } from "@/lib/api";
import { Mono } from "@/components/ui";

type Reverse = Record<string, { address: string; name: string | null; source: string | null; verified: boolean }>;

/** アドレスを ENS 名で表示する（GET /ens/reverse）。名前が無ければ短縮アドレス。
 *  承認者・Jury・レビュー投稿者・支払先など、人を指すアドレスに使う。 */
export function AddrName({ address, className = "" }: { address: string; className?: string }) {
  const a = address.toLowerCase();
  const { data } = useQuery({ queryKey: ["ens-reverse", a], queryFn: () => api<Reverse>(`/ens/reverse?address=${a}`), staleTime: 300_000, retry: false });
  const hit = data?.[a];
  if (hit?.name) return <span className={`inline-flex items-center gap-1 ${className}`} title={address}><Mono className="text-neutral-900">{hit.name}</Mono>{!hit.verified && <span className="text-[10px] text-neutral-400">(not written)</span>}</span>;
  return <Mono className={className}>{short(address)}</Mono>;
}
