export function BrandLogo({
  variant = "color",
  decorative = false,
}: {
  variant?: "color" | "monochrome" | "icon";
  decorative?: boolean;
}) {
  if (variant === "icon") {
    return <img src="/brand/easyrep-app-icon.webp" width={480} height={469} className="brand-image brand-image--icon" decoding="async" alt={decorative ? "" : "EasyRep"} />;
  }

  return (
    <span className={`brand-image brand-image--${variant} easyrep-wordmark`} role={decorative ? undefined : "img"} aria-label={decorative ? undefined : "EasyRep"} aria-hidden={decorative || undefined}>
      <img src="/brand/easyrep-app-icon.webp" width={480} height={469} decoding="async" alt="" />
      <span aria-hidden="true">EasyRep</span>
    </span>
  );
}
