# precios-pollo-pe

Precios y abastecimiento de pollo en Perú, extraídos de los boletines diarios de aves de MIDAGRI (SISAP / SIEA).

## Estructura

- `scripts/parse_boletin_aves.py`: parser del boletín diario (plantilla 2024–2026). Asigna columnas por posición y valida portada vs. tablas y coherencia entre boletines.
- `data/muestra/`: salida de ejemplo (boletines del 15 y 16-10-2026).
- `.github/workflows/test-gobpe.yml`: prueba de acceso de GitHub Actions a gob.pe (ejecución manual).

## Uso local

```bash
pip install -r requirements.txt
python scripts/parse_boletin_aves.py boletin-*.pdf --out salida/
```

Fuente: Ministerio de Desarrollo Agrario y Riego (MIDAGRI). Sitio no oficial.
