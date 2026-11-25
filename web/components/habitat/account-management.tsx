"use client";

import { useRef, useState, type FormEvent } from "react";
import { Building2, ChevronRight, Plus, ShieldCheck, UserRound, Users, X } from "lucide-react";
import { Sheet, SheetClose, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { enclosures } from "@/lib/habitat/enclosures";
import { accountEnclosures, applyAccountEdit, canManageAccount, demoStores, roleLabels, storeLabel, visibleAccounts, type DemoAccount } from "@/lib/habitat/accounts";

export function AccountManagement({ accounts, onChange, actorId, onActorChange }: {
  accounts: DemoAccount[];
  onChange: (accounts: DemoAccount[]) => void;
  actorId: string;
  onActorChange: (id: string) => void;
}) {
  const actor = accounts.find((account) => account.id === actorId) ?? accounts[0];
  const [draft, setDraft] = useState<DemoAccount | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const trigger = useRef<HTMLElement | null>(null);
  const rows = visibleAccounts(accounts, actor);
  const stores = demoStores.filter((store) => actor.role === "owner" || store.id === actor.storeId);
  const permittedEnclosures = accountEnclosures(actor);
  const editing = draft && accounts.some((account) => account.id === draft.id);

  function openEditor(account?: DemoAccount) {
    trigger.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    setError("");
    setNotice("");
    setDraft(account ? { ...account, enclosureIds: [...account.enclosureIds] } : {
      id: `demo-${Date.now()}`, name: "", role: "user", storeId: stores[0]?.id ?? null, enclosureIds: [], status: "active",
    });
  }
  function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!draft) return;
    const result = applyAccountEdit(accounts, actor.id, draft);
    if (result.error) { setError(result.error); return; }
    onChange(result.accounts);
    setNotice(`${draft.name.trim()} · 데모에 적용했습니다.`);
    setDraft(null);
  }

  return (
    <div className="account-workspace">
      <div className="account-preview-bar">
        <div><strong>계정·권한 미리보기</strong><p>변경은 이 화면의 데모에만 적용되며 새로고침하면 초기화됩니다.</p></div>
        <label><span>미리볼 계정</span><select value={actor.id} aria-label="미리볼 계정" onChange={(event) => { onActorChange(event.target.value); setNotice(""); }}>
          {accounts.map((account) => <option key={account.id} value={account.id} disabled={account.status === "paused"}>{account.name} · {roleLabels[account.role]}{account.status === "paused" ? " (사용 중지)" : ""}</option>)}
        </select></label>
      </div>
      <div className="account-hierarchy" aria-label="역할별 관리 범위">
        {([
          { role: "owner", icon: ShieldCheck, scope: "전체 매장", description: "매장 관리자·사용자 배정" },
          { role: "manager", icon: Building2, scope: "소속 매장", description: "매장 사용자·담당 사육장 관리" },
          { role: "user", icon: UserRound, scope: "배정된 사육장", description: "환경·기록 조회" },
        ] as const).map(({ role, icon: Icon, scope, description }) => (
          <section className={`panel account-role ${actor.role === role ? "is-current" : ""}`} key={role}>
            <div><Icon size={20} aria-hidden="true" /><h2>{roleLabels[role]}</h2>{actor.role === role && <span className="neutral-badge">현재 보기</span>}</div>
            <strong>{scope}</strong><p>{description}</p>
          </section>
        ))}
      </div>
      <section className="panel account-members">
        <div className="panel-heading">
          <div><h2><Users size={18} aria-hidden="true" /> {actor.role === "user" ? "내 계정" : "계정 관리"}</h2><p>{storeLabel(actor.storeId)} · {rows.length}명</p></div>
          {actor.role !== "user" && <button className="button primary" onClick={() => openEditor()}><Plus size={16} aria-hidden="true" /> 계정 추가</button>}
        </div>
        <div className="account-table-wrap">
          <table className="account-table"><thead><tr><th>계정</th><th>역할</th><th>소속·조회 범위</th><th>상태</th><th><span className="sr-only">계정 관리</span></th></tr></thead><tbody>
            {rows.map((account) => <tr key={account.id}>
              <td className="account-name"><strong>{account.name}</strong>{account.id === actor.id && <span className="neutral-badge">본인</span>}</td>
              <td className="account-role-cell">{roleLabels[account.role]}</td>
              <td className="account-scope"><strong>{storeLabel(account.storeId)}</strong><span>{account.role === "user" ? account.enclosureIds.map((id) => enclosures.find((item) => item.id === id)?.name).join(", ") || "사육장 배정 없음" : "소속 범위의 모든 사육장"}</span></td>
              <td className="account-state"><span className="neutral-badge">{account.status === "active" ? "사용 중" : "사용 중지"}</span></td>
              <td className="account-action">{canManageAccount(actor, account) ? <button className="button" onClick={() => openEditor(account)} aria-label={`${account.name} 계정 편집`}>편집 <ChevronRight size={15} aria-hidden="true" /></button> : <span className="muted">{account.id === actor.id ? "본인 변경 제한" : "변경 권한 없음"}</span>}</td>
            </tr>)}
          </tbody></table>
        </div>
        <p className="account-notice" role="status">{notice || (actor.role === "user" ? "계정·담당 사육장 변경은 매장 관리자에게 요청하세요." : "자기 계정과 같은 단계·상위 계정의 권한은 변경할 수 없습니다.")}</p>
      </section>
      <section className="panel account-access-summary">
        <div><h2>이 계정의 권한</h2><p>{actor.name} · {roleLabels[actor.role]}</p></div>
        <dl><div><dt>사육장 조회</dt><dd>{permittedEnclosures.length}개</dd></div><div><dt>계정 관리</dt><dd>{actor.role === "owner" ? "전체 매장의 하위 계정" : actor.role === "manager" ? "소속 매장 사용자" : "권한 없음"}</dd></div><div><dt>운영 권한</dt><dd>{actor.role === "user" ? "조회 전용" : "제어·설정 관리 예정"}</dd></div></dl>
        <p className="account-integration-note">실제 로그인·초대·서버 권한 검증은 미연동입니다. 위 계정 선택은 이 관리 화면의 미리보기에만 적용됩니다.</p>
      </section>
      <Sheet open={!!draft} onOpenChange={(open) => { if (!open) setDraft(null); }}>
        <SheetContent className="record-sheet account-editor" showCloseButton={false} onCloseAutoFocus={(event) => { event.preventDefault(); trigger.current?.focus({ preventScroll: true }); }}>
          <SheetHeader><SheetTitle>{editing ? "계정 편집" : "계정 추가"}</SheetTitle><SheetDescription>{actor.name}의 관리 범위 · 데모</SheetDescription></SheetHeader>
          <SheetClose asChild><button className="sheet-close" aria-label="계정 편집 닫기"><X size={18} /></button></SheetClose>
          {draft && <form onSubmit={save} className="account-form">
            <label><span>이름</span><input autoComplete="off" value={draft.name} maxLength={40} required onChange={(event) => setDraft({ ...draft, name: event.target.value })} /></label>
            <label><span>역할</span><select value={draft.role} onChange={(event) => setDraft({ ...draft, role: event.target.value as DemoAccount["role"], enclosureIds: [] })}>
              {actor.role === "owner" && <option value="manager">매장 관리자</option>}<option value="user">사용자</option>
            </select></label>
            <label><span>소속 매장</span><select value={draft.storeId ?? ""} disabled={actor.role === "manager"} onChange={(event) => setDraft({ ...draft, storeId: event.target.value, enclosureIds: [] })}>
              {stores.map((store) => <option key={store.id} value={store.id}>{store.name}</option>)}
            </select></label>
            {draft.role === "user" ? <fieldset><legend>담당 사육장</legend><p>선택한 사육장의 환경·기록을 조회합니다.</p>
              {enclosures.filter((item) => demoStores.find((store) => store.id === draft.storeId)?.enclosureIds.includes(item.id)).map((item) => <label className="account-enclosure-option" key={item.id}>
                <input type="checkbox" checked={draft.enclosureIds.includes(item.id)} onChange={(event) => setDraft({ ...draft, enclosureIds: event.target.checked ? [...draft.enclosureIds, item.id] : draft.enclosureIds.filter((id) => id !== item.id) })} /><span>{item.name}</span>
              </label>)}
            </fieldset> : <p className="account-field-note">매장 관리자는 소속 매장의 모든 사육장과 사용자를 관리합니다.</p>}
            <label><span>계정 상태</span><select value={draft.status} onChange={(event) => setDraft({ ...draft, status: event.target.value as DemoAccount["status"] })}><option value="active">사용 중</option><option value="paused">사용 중지</option></select></label>
            {error && <p className="warning-text" role="alert">{error}</p>}
            <p className="account-field-note">실제 계정은 생성·변경되지 않습니다.</p>
            <div className="account-editor-actions"><button className="button" type="button" onClick={() => setDraft(null)}>취소</button><button className="button primary" type="submit">데모에 적용</button></div>
          </form>}
        </SheetContent>
      </Sheet>
    </div>
  );
}
