/**
 * Demo CLI del cliente UTE TS.
 * Uso:  tsx demo.ts [documento]
 *  - password: env UTE_PASSWORD (preferido) o stdin oculto.
 */
import { createInterface } from "node:readline/promises";
import { stdin, stdout } from "node:process";
import { UteClient } from "./src/index.js";

async function ask(prompt: string, hidden = false): Promise<string> {
  const rl = createInterface({ input: stdin, output: stdout, terminal: true });
  if (hidden) {
    // muteo el output de readline para no echo del password
    const orig = (stdout as unknown as { write: typeof stdout.write }).write;
    (stdout as unknown as { write: typeof stdout.write }).write = (
      chunk: string | Uint8Array,
    ): boolean => orig.call(stdout, typeof chunk === "string" && chunk !== "\n" && chunk !== "\r\n" ? "" : chunk);
    try {
      const ans = await rl.question(prompt);
      return ans;
    } finally {
      (stdout as unknown as { write: typeof stdout.write }).write = orig;
      rl.close();
      stdout.write("\n");
    }
  }
  const ans = await rl.question(prompt);
  rl.close();
  return ans;
}

async function main() {
  const doc = process.argv[2] ?? (await ask("Documento (CI/RUT/BPS): "));
  const pwd = process.env.UTE_PASSWORD ?? (await ask("Contraseña: ", true));
  if (!doc || !pwd) {
    console.error("documento y contraseña son requeridos");
    process.exit(1);
  }
  const ute = new UteClient();
  await ute.bootstrap();
  await ute.login(doc, pwd);
  console.log("✓ login OK");

  for (const acc of await ute.accounts()) {
    console.log(`\n▶ Cuenta ${acc.accountId} — ${acc.address}`);
    const debt = await ute.totalDebt(acc.accountId);
    const bp = await ute.billingPeriodSummary(acc.accountId);
    console.log(`  Deuda: $${debt.toLocaleString("es-UY")}`);
    console.log(
      `  Período ${bp.initialDate} → ${bp.finalDate}: ${bp.currentConsumptionKwh.toFixed(1)} kWh / $${bp.currentSpendingUyu.toLocaleString("es-UY")}`,
    );

    for (const svc of await ute.services(acc.accountId)) {
      console.log(
        `  Suministro ${svc.servicePointId} (${svc.tariffDescription}) — ${svc.address}`,
      );
      console.log(
        `    Voltaje ${svc.voltage} | ${svc.serviceType} | Pot. punta ${svc.contractedPowerOnPeak} kW | AMI ${svc.amiPresent} (${svc.amiType ?? "-"})`,
      );
      const today = new Date();
      const start = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-01`;
      const end = today.toISOString().slice(0, 10);
      const tous = await ute.consumptionByTou(
        svc.servicePointId,
        svc.tariff || "TRD",
        start,
        end,
      );
      const total = tous.reduce((a, t) => a + t.consumption, 0);
      console.log(`    Consumo ${start}–${end}: ${total.toFixed(1)} kWh`);
      for (const t of tous)
        console.log(`      ${t.tou.padEnd(6)} ${t.consumption.toFixed(1)} ${t.uom}`);
    }
  }
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
