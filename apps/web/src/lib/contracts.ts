export const escrowAbi = [
  { type: "function", name: "openCase", stateMutability: "nonpayable", inputs: [{ name: "caseId", type: "bytes32" }, { name: "token", type: "address" }, { name: "approvers", type: "address[]" }, { name: "threshold", type: "uint8" }], outputs: [] },
  { type: "function", name: "getCase", stateMutability: "view", inputs: [{ name: "caseId", type: "bytes32" }], outputs: [{ type: "tuple", components: [{ name: "client", type: "address" }, { name: "token", type: "address" }, { name: "approvers", type: "address[]" }, { name: "threshold", type: "uint8" }] }] },
  { type: "function", name: "getTask", stateMutability: "view", inputs: [{ name: "caseId", type: "bytes32" }, { name: "taskId", type: "bytes32" }], outputs: [{ type: "tuple", components: [{ name: "amount", type: "uint256" }, { name: "payee", type: "address" }, { name: "deliverableHash", type: "bytes32" }, { name: "approvalCount", type: "uint8" }, { name: "status", type: "uint8" }] }] },
] as const;

export const erc20Abi = [
  { type: "function", name: "approve", stateMutability: "nonpayable", inputs: [{ name: "spender", type: "address" }, { name: "amount", type: "uint256" }], outputs: [{ type: "bool" }] },
  { type: "function", name: "allowance", stateMutability: "view", inputs: [{ name: "owner", type: "address" }, { name: "spender", type: "address" }], outputs: [{ type: "uint256" }] },
  { type: "function", name: "balanceOf", stateMutability: "view", inputs: [{ name: "a", type: "address" }], outputs: [{ type: "uint256" }] },
  { type: "function", name: "mint", stateMutability: "nonpayable", inputs: [{ name: "to", type: "address" }, { name: "amount", type: "uint256" }], outputs: [] },
] as const;
