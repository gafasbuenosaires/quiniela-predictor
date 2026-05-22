# Quiniela Predictor — Multi-provincia

App web que se **ejecuta sola**, abre el navegador y **se actualiza automáticamente** (datos cada 15 min, pantalla cada 2 min).

## Provincias incluidas

| Provincia | Histórico |
|-----------|-----------|
| Nacional (Ciudad) | ~30 días |
| Buenos Aires | Hoy + ayer (se acumula con el tiempo) |
| Santa Fe | Hoy + ayer |
| Córdoba | Hoy + ayer |

Fuente: [quini-6-resultados.com.ar](https://www.quini-6-resultados.com.ar/quinielas/) (no oficial).

## Inicio rápido (Windows)

**Doble clic en `INICIAR.bat`** o en PowerShell:

```powershell
cd c:\Quiniela
.\run.ps1
```

Se abre solo: **http://127.0.0.1:8000**

## Interfaz

- **Todas**: vista general con predicción por provincia
- **Cada provincia**: detalle, monitoreo, IA 5d, stats 30d, martingala ×7
- **Auto**: refresco de pantalla y sincronización en segundo plano
- **Sincronizar**: fuerza descarga de las 4 provincias

## Configuración opcional

Archivo `.env`:

```env
OPENAI_API_KEY=sk-...
OPEN_BROWSER=0
APP_URL=http://127.0.0.1:8000
```

## Aviso

La quiniela es aleatoria. Esta app no garantiza ganancias. Juego responsable.
