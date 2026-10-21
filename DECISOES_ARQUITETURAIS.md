# Decisões arquiteturais — especificação V1

Este documento descreve desenho, não serviços implantados ou contas configuradas.

1. **Monólito modular:** Python 3.13, API e workers separados por processo, mesma base de código; OpenAPI 3.1 e JSON Schema 2020-12.
2. **Persistência exclusiva:** PostgreSQL próprio, volumes/backups dedicados, catálogo global e dados privados separados; fila/outbox transacionais.
3. **Identidade:** issuer+sub canônico; tenant derivado de sessão; account_created_at imutável e provisionamento transacional idempotente.
4. **Autorização:** RLS forçada com papéis mínimos, contexto transacional e reset de pool; serviço revalida owner. Prova SQL fica na 02.
5. **Ingestão atômica:** lote versionado de produtor autorizado, nenhum registro parcial; recibo estável e conflito se a mesma chave tiver conteúdo diferente.
6. **Publicações:** vaga lógica e evento distintos; published_at é instante efetivo original/republicado. Prova governada e predecessor; correção não muda instante ou ressuscita vaga.
7. **IA estruturada:** classificação global, perfil/matching privados, evidências e incerteza. Modelo/custo dependem de benchmark autorizado; sem orçamento financeiro interno.
8. **Currículo efêmero:** PDF e texto em área transitória protegida contra swap/dumps/spool; fila só com handle/owner/geração/epoch/TTL. Perda do arquivo pede novo upload.
9. **Exclusão:** revogação imediata, expurgo ativo em até 24h e backups até 30 dias; ledger mínimo transitório saneia restore antes de liberar leitura/egress. Prova operacional futura obrigatória.
10. **Sincronização:** sequence na disponibilização, watermark/cursor autenticado, bootstrap após expiração, ACK explícito. Candidatura pertence ao evento; republicação não herda estado.
11. **TTS existente:** adaptador dedicado, template mínimo, identidade própria, timeout, privacidade e custo autorizados. Nenhuma conexão genérica a outros projetos.
12. **CI:** testes offline curtos; suites pesadas em workers próprios, descartáveis e segregados. Nenhum fallback pesado no control plane. CI não recebe chaves reais.
13. **Governança:** código público só após auditoria/autorizações; histórico inicial independente. Main exige PR/checks, sem force-push/deleção/bypass administrativo; sem segundo revisor obrigatório com um mantenedor.
14. **Entrega em dez passadas:** APK controlado na 09; Google/HTTPS público/4G/TTS reais na 10. Gates externos bloqueiam apenas seu uso dependente.
15. **Rollback:** distinguir exposição, aplicação, consumidores, schema e dados; backup externo e restore antes de promoção, sem afetar outros projetos.

Mudança de produto, custo, privacidade ou fronteira exige revisão do proprietário.
A preparação deste candidato não autoriza publicação, proteção remota, merge ou a 02.
