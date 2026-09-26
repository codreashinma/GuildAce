"use client";

import { connectorsForWallets } from "@rainbow-me/rainbowkit";
import { injectedWallet, metaMaskWallet, rabbyWallet, walletConnectWallet } from "@rainbow-me/rainbowkit/wallets";
import { createConfig, http } from "wagmi";
import { sepolia } from "wagmi/chains";

const projectId = process.env.NEXT_PUBLIC_WC_PROJECT_ID || "choice-dev";

// Coinbase Wallet は依存（@coinbase/cdp-sdk → @x402）が Next のビルドで解決できないため外している
const connectors = connectorsForWallets(
  [{ groupName: "Wallets", wallets: [metaMaskWallet, rabbyWallet, injectedWallet, walletConnectWallet] }],
  { appName: "GuildAce — Digital Company Marketplace", projectId },
);

export const wagmiConfig = createConfig({
  connectors,
  chains: [sepolia],
  transports: { [sepolia.id]: http() },
  ssr: true,
});
