/** Greeting by the viewer's own clock (the business date shown on the Overview stays fixed). */
export function greeting(displayName: string, now = new Date()): string {
  const hour = now.getHours();
  const part = hour >= 5 && hour < 12 ? "Good morning" : hour >= 12 && hour < 18 ? "Good afternoon" : "Good evening";
  const name = displayName.trim();
  return name ? `${part}, ${name}` : part;
}
