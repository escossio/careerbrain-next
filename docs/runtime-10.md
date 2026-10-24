# Runtime persistente — passada 10

O runtime usa três serviços independentes: PostgreSQL, uma migração administrativa
de execução única e API WSGI. A topologia, os endereços, os arquivos de ambiente,
os Docker secrets e os backups ficam exclusivamente no ambiente operacional privado.

## Operação

1. Renderizar o `pg_hba.conf` privado a partir do template e criar secrets por papel
   com permissões restritas.
2. Validar o Compose com seus arquivos privados; iniciar PostgreSQL e aguardar o
   healthcheck.
3. Executar a migração somente com `CBN_MIGRATION_CONFIRM` igual ao banco de destino.
   O comando recusa destino ausente, divergente ou papel diferente de `cb_migrator`.
4. Iniciar a API; `/healthz` indica processo vivo e `/readyz` confirma os pools de
   banco. O servidor WSGI de produção é Gunicorn; `wsgiref` permanece exclusivo do
   smoke descartável.

O banco não publica portas Docker e deve escutar somente na rede interna dedicada.
O healthcheck da API é local ao container e não substitui uma prova de exposição
autorizada. Logs não devem registrar headers, corpos, tokens, currículos ou PII.

## Backup, restore e rollback

O backup é `pg_dump` em formato custom, salvo somente no armazenamento privado
autorizado. A restauração é comprovada em banco temporário isolado antes de ser
considerada utilizável. Nunca adicionar dump ou relatório com dados reais ao Git.

Para rollback da aplicação, parar apenas API e iniciar uma imagem previamente
validada contra o mesmo esquema. Migrações sem `down` recusam downgrade destrutivo;
o rollback de dados é restauração controlada de backup, seguido da reaplicação de
ledger e das verificações de privacidade previstas. Não usar `docker compose down`
com remoção de volumes nem remoção global de imagens/volumes.
