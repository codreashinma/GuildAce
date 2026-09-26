"use client";

import { useCallback } from "react";
import { useAccount, useSwitchChain } from "wagmi";
import { sepolia } from "wagmi/chains";

/** 書き込み・署名の前に接続チェーンを Sepolia にそろえる。別チェーンなら MetaMask 等に切替を促す。 */
export function useEnsureSepolia() {
  const { chainId, isConnected } = useAccount();
  const { switchChainAsync } = useSwitchChain();
  return useCallback(async () => {
    if (!isConnected) throw new Error("Please connect your wallet first");
    if (chainId !== sepolia.id) await switchChainAsync({ chainId: sepolia.id });
  }, [chainId, isConnected, switchChainAsync]);
}

/** モック時に API へ報告する疑似 tx hash。`0xmock` で始まるので Etherscan リンクにはならない */
export const mockTxHash = () => "0xmock" + Array.from(crypto.getRandomValues(new Uint8Array(29))).map((b) => b.toString(16).padStart(2, "0")).join("");
