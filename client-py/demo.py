"""Demo CLI del cliente UTE.

Uso:
    python demo.py [documento]
    # password: env UTE_PASSWORD o se pide por stdin (oculto)
"""
import asyncio
import logging
import os
import sys
from getpass import getpass

from ute_client import UteClient


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if len(sys.argv) > 2:
        print(__doc__)
        sys.exit(1)
    doc = sys.argv[1] if len(sys.argv) == 2 else input("Documento (CI/RUT/BPS): ").strip()
    pwd = os.environ.get("UTE_PASSWORD") or getpass("Contraseña: ")

    async with UteClient() as c:
        await c.bootstrap()
        await c.login(doc, pwd)
        print(f"\n✓ login OK")

        for acc in await c.accounts():
            print(f"\n▶ Cuenta {acc.account_id} — {acc.address}")
            print(f"  Alias: {acc.alias!r}")
            print(f"  Mensajes sin leer: {await c.messages_unread()}")
            print(f"  Deuda total: ${await c.total_debt(acc.account_id):,.2f} UYU")
            bp = await c.billing_period_summary(acc.account_id)
            print(
                f"  Período actual {bp.initial_date} → {bp.final_date}: "
                f"{bp.current_consumption_kwh:.1f} kWh / ${bp.current_spending_uyu:,.2f} UYU"
            )

            for svc in await c.services(acc.account_id):
                print(
                    f"\n  Suministro {svc.service_point_id} ({svc.tariff_description})"
                )
                print(
                    f"    {svc.address}, {svc.city}, {svc.department} ({svc.zip_code})"
                )
                print(
                    f"    Voltaje: {svc.voltage} | Tipo: {svc.service_type} | Pot. punta: {svc.contracted_power_on_peak} kW"
                )
                print(
                    f"    Medidor: {svc.meter_id} | AMI: {svc.ami_present} ({svc.ami_type or '-'})"
                )

                status = await c.supply_status(
                    acc.account_id, svc.service_agreement_id, svc.service_point_id
                )
                print(
                    f"    Status: {'INTERRUMPIDO' if status['isInterrupted'] else 'OK'}"
                )

                # Consumo del mes corriente
                from datetime import date

                today = date.today()
                start = today.replace(day=1).isoformat()
                end = today.isoformat()
                # Plan code = código del tariff del cliente (TRD/TRT/TRS).
                tous = await c.consumption_by_tou(
                    svc.service_point_id, plan=svc.tariff or "TRD", date_from=start, date_to=end
                )
                total = sum(t.consumption for t in tous)
                print(f"    Consumo {start}–{end}: {total:.1f} kWh")
                for tou in tous:
                    print(f"      {tou.tou:6s} {tou.consumption:6.1f} {tou.uom}")


if __name__ == "__main__":
    asyncio.run(main())
