import { enclosures } from "./enclosures";

export type AccountRole = "owner" | "manager" | "user";
export type DemoAccount = {
  id: string;
  name: string;
  role: AccountRole;
  storeId: string | null;
  enclosureIds: string[];
  status: "active" | "paused";
};
export const roleLabels: Record<AccountRole, string> = {
  owner: "총괄 관리자", manager: "매장 관리자", user: "사용자",
};
export const demoStores = [
  { id: "store-a", name: "매장 A", enclosureIds: ["crested-01", "leopard-02"] },
  { id: "store-b", name: "매장 B", enclosureIds: ["python-03", "new-04"] },
];
export const demoAccounts: DemoAccount[] = [
  { id: "owner", name: "총괄 담당자", role: "owner", storeId: null, enclosureIds: [], status: "active" },
  { id: "manager-a", name: "매장 A 관리자", role: "manager", storeId: "store-a", enclosureIds: [], status: "active" },
  { id: "manager-b", name: "매장 B 관리자", role: "manager", storeId: "store-b", enclosureIds: [], status: "active" },
  { id: "user-a", name: "매장 A 사용자 01", role: "user", storeId: "store-a", enclosureIds: ["crested-01"], status: "active" },
  { id: "user-a2", name: "매장 A 사용자 02", role: "user", storeId: "store-a", enclosureIds: ["leopard-02"], status: "active" },
  { id: "user-b", name: "매장 B 사용자 01", role: "user", storeId: "store-b", enclosureIds: ["python-03"], status: "active" },
];

// UI simulation only. Real sessions and server authorization are not connected.
export function canManageAccount(actor: DemoAccount, target: DemoAccount) {
  if (actor.status !== "active" || actor.id === target.id || target.role === "owner") return false;
  return actor.role === "owner" || (actor.role === "manager" && target.role === "user" && actor.storeId === target.storeId);
}
export function visibleAccounts(accounts: DemoAccount[], actor: DemoAccount) {
  return accounts.filter((account) => account.id === actor.id || canManageAccount(actor, account));
}
export function accountEnclosures(account: DemoAccount) {
  if (account.status !== "active") return [];
  if (account.role === "owner") return enclosures;
  const store = demoStores.find((item) => item.id === account.storeId);
  return enclosures.filter((item) => store?.enclosureIds.includes(item.id)
    && (account.role === "manager" || account.enclosureIds.includes(item.id)));
}
export function storeLabel(storeId: string | null) {
  return demoStores.find((store) => store.id === storeId)?.name ?? "전체 매장";
}
export function applyAccountEdit(accounts: DemoAccount[], actorId: string, draft: DemoAccount): { accounts: DemoAccount[]; error?: string } {
  const fail = (error: string) => ({ accounts, error });
  const actor = accounts.find((account) => account.id === actorId);
  const existing = accounts.find((account) => account.id === draft.id);
  if (!actor || (existing && !canManageAccount(actor, existing)) || !canManageAccount(actor, draft))
    return fail("이 계정을 변경할 권한이 없습니다.");
  if (!["manager", "user"].includes(draft.role) || !["active", "paused"].includes(draft.status))
    return fail("역할과 계정 상태를 확인하세요.");
  const name = draft.name.trim();
  if (!name || name.length > 40) return fail("이름을 1~40자로 입력하세요.");
  const store = demoStores.find((item) => item.id === draft.storeId);
  if (!store) return fail("소속 매장을 선택하세요.");
  if (draft.enclosureIds.some((id) => !store.enclosureIds.includes(id)))
    return fail("소속 매장의 사육장만 배정할 수 있습니다.");
  const updated = { ...draft, name, enclosureIds: draft.role === "user" ? [...new Set(draft.enclosureIds)] : [] };
  return { accounts: existing ? accounts.map((account) => account.id === updated.id ? updated : account) : [...accounts, updated] };
}
