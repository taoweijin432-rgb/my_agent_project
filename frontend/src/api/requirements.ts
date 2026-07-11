import type { RequirementPoint } from "./types";

export function parseRequirements(value: string): RequirementPoint[] {
  return value
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line, index) => {
      const [idPart, titlePart, keywordsPart, priorityPart] = line.split("|").map((part) => part.trim());
      const priority = isPriority(priorityPart) ? priorityPart : "medium";
      return {
        id: idPart || `REQ-${String(index + 1).padStart(3, "0")}`,
        title: titlePart || idPart || `需求点 ${index + 1}`,
        description: titlePart || idPart || `需求点 ${index + 1}`,
        keywords: splitTags(keywordsPart || titlePart || idPart),
        priority,
        source: "frontend"
      };
    });
}

export function splitTags(value: string): string[] {
  return value
    .split(/[,，\n]/)
    .map((tag) => tag.trim())
    .filter(Boolean);
}

function isPriority(value: string | undefined): value is RequirementPoint["priority"] {
  return value === "low" || value === "medium" || value === "high" || value === "critical";
}
