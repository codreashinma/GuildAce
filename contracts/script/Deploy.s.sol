// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import {Script, console} from "forge-std/Script.sol";
import {Escrow} from "../src/Escrow.sol";
import {MockUSDC} from "../src/MockUSDC.sol";

/// 使い方:
///   forge script script/Deploy.s.sol --rpc-url sepolia --broadcast --private-key $DEPLOYER_PRIVATE_KEY
/// OPS_ADDRESS（API のサーバー署名者 = チェーン連携ワーカーのアドレス）を env に設定しておく。
contract Deploy is Script {
    function run() external {
        address ops = vm.envAddress("OPS_ADDRESS");
        vm.startBroadcast();
        MockUSDC usdc = new MockUSDC();
        Escrow escrow = new Escrow(ops);
        vm.stopBroadcast();
        console.log("MockUSDC:", address(usdc));
        console.log("Escrow:  ", address(escrow));
        console.log("Ops:     ", ops);
    }
}
