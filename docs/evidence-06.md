# Evidência técnica da passada 06

A certificação final registrará a execução em PostgreSQL descartável e sem rede,
com PDFs sintéticos. Os casos cobrem sucesso, incerteza, limites defensivos,
idempotência, geração/epoch, cancelamento, interrupção, perda de temporário,
expiração, limpeza, isolamento de tenant e limites de memória/swap/core dump.

O teste prova somente o runtime isolado. Currículos reais, tráfego de IA e a
proteção do ambiente produtivo permanecem fora desta execução.
