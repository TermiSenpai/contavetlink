/**
 * guard-destructive.js
 * 
 * Hook script para PreToolUse > Bash
 * Bloquea comandos SQL/filesystem destructivos.
 * 
 * Ubicar en: .claude/hooks/guard-destructive.js
 * Referencia en settings.json:
 *   "command": "node .claude/hooks/guard-destructive.js"
 * 
 * Compatible con Windows, macOS y Linux.
 */

let input = "";

process.stdin.setEncoding("utf8");
process.stdin.on("data", (chunk) => (input += chunk));
process.stdin.on("end", () => {
  try {
    const data = JSON.parse(input);
    const cmd = (data.tool_input?.command || "").toUpperCase();

    const destructivePatterns = [
      /DROP\s+(TABLE|DATABASE)/,
      /DELETE\s+FROM\s+\S+\s*;/,
      /TRUNCATE\s+TABLE/,
      /RM\s+-RF\s+\//,
      /FORMAT\s+[A-Z]:/,          // Windows format drive
      /DEL\s+\/S\s+\/Q/,          // Windows recursive delete
      /RMDIR\s+\/S\s+\/Q/,        // Windows recursive rmdir
    ];

    const match = destructivePatterns.find((p) => p.test(cmd));

    if (match) {
      const output = {
        decision: "deny",
        reason: `Comando destructivo bloqueado: coincide con patron ${match}. Ejecuta manualmente si es intencional.`,
      };
      process.stdout.write(JSON.stringify(output));
      process.exit(2);
    }
  } catch (e) {
    // Si falla el parsing, no bloquear — fail open
    // Puedes cambiar a process.exit(2) si prefieres fail closed
  }

  process.exit(0);
});