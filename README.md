# Importador Universal MySQL v5

Versión blindada para tablas MySQL ya existentes con columnas en formato CamelCase y Excel con columnas `snake_case`.

Ejemplo corregido automáticamente:

- `work_request_no` -> `WorkRequestNo`
- `work_request_key` -> `WorkRequestKey`
- `approved_date` -> `ApprovedDate`
- `due_date` -> `DueDate`

También conserva:

- Reparación temporal de `.xlsx` con estilos corruptos `undefined`.
- Detección automática de columnas.
- `ON DUPLICATE KEY UPDATE`.
- Creación automática de columnas faltantes.
- Logs.
- GUI Tkinter.
- Configuración con `config.ini`.

## Recomendación para tu caso

En `config.ini` usa:

```ini
[import]
unique_keys = auto
```

La app detectará `WorkRequestNo` / `WorkRequestKey` después del mapeo.
