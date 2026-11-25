import { ArrowUpRight, ChartNoAxesCombined } from "lucide-react";
import { Empty, EmptyHeader, EmptyTitle, EmptyDescription, EmptyMedia } from "@/components/ui/empty";

export function Unregistered({ onManage }: { onManage: () => void }) {
  return (
    <Empty className="empty-state">
      <EmptyHeader>
        <EmptyMedia variant="icon">
          <ChartNoAxesCombined />
        </EmptyMedia>
        <EmptyTitle>등록된 센서가 없습니다</EmptyTitle>
        <EmptyDescription>
          센서를 등록하면 현재 환경과 측정 이력을 확인할 수 있습니다.
        </EmptyDescription>
      </EmptyHeader>
      <button className="button primary" onClick={onManage}>
        센서 등록 정보 보기 <ArrowUpRight size={15} />
      </button>
    </Empty>
  );
}
