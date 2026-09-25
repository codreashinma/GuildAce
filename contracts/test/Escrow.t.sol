// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import {Test} from "forge-std/Test.sol";
import {Escrow} from "../src/Escrow.sol";
import {MockUSDC} from "../src/MockUSDC.sol";

contract EscrowTest is Test {
    Escrow escrow;
    MockUSDC usdc;

    address arbiter = makeAddr("arbiter");
    address client = makeAddr("client");
    address agent = makeAddr("agent");
    address worker = makeAddr("worker");
    address stranger = makeAddr("stranger");

    bytes32 constant CASE_ID = keccak256("case-1");
    uint256 constant AMOUNT = 300e6;

    function setUp() public {
        usdc = new MockUSDC();
        escrow = new Escrow(arbiter);
        usdc.mint(client, 1_000e6);
        vm.prank(client);
        usdc.approve(address(escrow), type(uint256).max);
    }

    function _deposit() internal {
        vm.prank(client);
        escrow.deposit(CASE_ID, address(usdc), AMOUNT);
    }

    function _split() internal view returns (address[] memory r, uint256[] memory a) {
        r = new address[](2);
        a = new uint256[](2);
        r[0] = agent;
        r[1] = worker;
        a[0] = 250e6;
        a[1] = 50e6;
    }

    function test_deposit() public {
        _deposit();
        Escrow.Case memory c = escrow.getCase(CASE_ID);
        assertEq(c.client, client);
        assertEq(c.amount, AMOUNT);
        assertEq(uint256(c.status), uint256(Escrow.Status.Funded));
        assertEq(usdc.balanceOf(address(escrow)), AMOUNT);
    }

    function test_deposit_revertsWhenAlreadyFunded() public {
        _deposit();
        vm.prank(client);
        vm.expectRevert(Escrow.AlreadyFunded.selector);
        escrow.deposit(CASE_ID, address(usdc), AMOUNT);
    }

    function test_release_byClient() public {
        _deposit();
        (address[] memory r, uint256[] memory a) = _split();
        vm.prank(client);
        escrow.release(CASE_ID, r, a);
        assertEq(usdc.balanceOf(agent), 250e6);
        assertEq(usdc.balanceOf(worker), 50e6);
        assertEq(usdc.balanceOf(address(escrow)), 0);
        assertEq(uint256(escrow.getCase(CASE_ID).status), uint256(Escrow.Status.Released));
    }

    function test_release_revertsForNonClient() public {
        _deposit();
        (address[] memory r, uint256[] memory a) = _split();
        vm.prank(stranger);
        vm.expectRevert(Escrow.NotClient.selector);
        escrow.release(CASE_ID, r, a);
        // arbiter も release はできない（resolve のみ）
        vm.prank(arbiter);
        vm.expectRevert(Escrow.NotClient.selector);
        escrow.release(CASE_ID, r, a);
    }

    function test_release_revertsOnSumMismatch() public {
        _deposit();
        (address[] memory r, uint256[] memory a) = _split();
        a[1] = 49e6;
        vm.prank(client);
        vm.expectRevert(Escrow.SumMismatch.selector);
        escrow.release(CASE_ID, r, a);
    }

    function test_resolve_refundByArbiter() public {
        _deposit();
        address[] memory r = new address[](1);
        uint256[] memory a = new uint256[](1);
        r[0] = client;
        a[0] = AMOUNT;
        vm.prank(arbiter);
        escrow.resolve(CASE_ID, r, a);
        assertEq(usdc.balanceOf(client), 1_000e6);
        assertEq(uint256(escrow.getCase(CASE_ID).status), uint256(Escrow.Status.Resolved));
    }

    function test_resolve_revertsForNonArbiter() public {
        _deposit();
        (address[] memory r, uint256[] memory a) = _split();
        vm.prank(client);
        vm.expectRevert(Escrow.NotArbiter.selector);
        escrow.resolve(CASE_ID, r, a);
    }

    function test_cannotReleaseTwice() public {
        _deposit();
        (address[] memory r, uint256[] memory a) = _split();
        vm.startPrank(client);
        escrow.release(CASE_ID, r, a);
        vm.expectRevert(Escrow.NotFunded.selector);
        escrow.release(CASE_ID, r, a);
        vm.stopPrank();
    }
}
