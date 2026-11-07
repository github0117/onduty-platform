/** 逗号、中文逗号或换行分隔的多值输入，去掉空白与空项。 */
export function splitDraftList(raw: string): string[] {
  return raw
    .split(/[,，\n]/)
    .map((value) => value.trim())
    .filter(Boolean);
}
