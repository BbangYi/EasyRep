export type AuthSession = {
  csrfToken: string;
  user: {
    id: string;
    name: string;
    loginId: string;
    role: "owner" | "manager" | "user";
    roleLabel: string;
    storeName: string;
  };
  enclosures: { id: string; name: string }[];
  site: { title: string; notice: string };
};

export const managementLabels: Record<AuthSession["user"]["role"], string> = {
  owner: "사이트·계정 관리",
  manager: "매장·사용자 관리",
  user: "내 배정 정보",
};
