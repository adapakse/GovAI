-- GovAI — Tłumaczenia treści katalogowych (ai_act_requirements, app_settings, providers)
--
-- PLIK GENEROWANY — NIE EDYTUJ RĘCZNIE. Źródło: db/i18n/<locale>/*.json,
-- generator: node scripts/gen-db-i18n.mjs --locales pt --out 018_i18n_content_pt.sql
--
-- Kolumna bazowa (polski) nie jest zmieniana; uzupełniane są kolumny *_i18n.
-- Tłumaczenia już zapisane w bazie (np. poprawione w UI) wygrywają; pliki uzupełniają brakujące języki.
-- Idempotentna — deploy-remote.sh uruchamia wszystkie migracje przy każdym deployu.

-- ── ai_act_requirements ───────────────────────────────────────────────────
UPDATE ai_act_requirements SET title_i18n = '{"pt":"Dados e governação de dados"}'::jsonb || COALESCE(title_i18n, '{}'::jsonb),
    text_i18n = '{"pt":"Os conjuntos de dados de treino, validação e teste devem cumprir critérios de qualidade — pertinência, representatividade, ausência de erros e completude. É exigida a documentação dos conjuntos de dados."}'::jsonb || COALESCE(text_i18n, '{}'::jsonb)
  WHERE risk_level = 'high'::risk_level AND article_ref = 'Art. 10';
UPDATE ai_act_requirements SET title_i18n = '{"pt":"Documentação técnica"}'::jsonb || COALESCE(title_i18n, '{}'::jsonb),
    text_i18n = '{"pt":"É exigida documentação técnica completa, em conformidade com o anexo IV do EU AI Act, antes da colocação do sistema no mercado ou da sua colocação em serviço. A documentação deve ser mantida atualizada ao longo de todo o ciclo de vida do sistema."}'::jsonb || COALESCE(text_i18n, '{}'::jsonb)
  WHERE risk_level = 'high'::risk_level AND article_ref = 'Art. 11';
UPDATE ai_act_requirements SET title_i18n = '{"pt":"Transparência e prestação de informações"}'::jsonb || COALESCE(title_i18n, '{}'::jsonb),
    text_i18n = '{"pt":"O sistema de IA deve garantir a transparência do seu funcionamento. Os utilizadores devem ser informados de que estão a interagir com um sistema de IA e compreender o seu funcionamento na medida necessária para a supervisão."}'::jsonb || COALESCE(text_i18n, '{}'::jsonb)
  WHERE risk_level = 'high'::risk_level AND article_ref = 'Art. 13';
UPDATE ai_act_requirements SET title_i18n = '{"pt":"Supervisão humana"}'::jsonb || COALESCE(title_i18n, '{}'::jsonb),
    text_i18n = '{"pt":"Existem medidas que permitem às pessoas singulares compreender, acompanhar e intervir no funcionamento do sistema de IA. Deve ser possível interromper ou reverter qualquer decisão tomada pelo sistema."}'::jsonb || COALESCE(text_i18n, '{}'::jsonb)
  WHERE risk_level = 'high'::risk_level AND article_ref = 'Art. 14';
UPDATE ai_act_requirements SET title_i18n = '{"pt":"Exatidão e solidez"}'::jsonb || COALESCE(title_i18n, '{}'::jsonb),
    text_i18n = '{"pt":"O sistema deve alcançar um nível adequado de exatidão ao longo de todo o seu ciclo de vida. São exigidos testes de resistência a erros, ataques e entradas inesperadas."}'::jsonb || COALESCE(text_i18n, '{}'::jsonb)
  WHERE risk_level = 'high'::risk_level AND article_ref = 'Art. 15';
UPDATE ai_act_requirements SET title_i18n = '{"pt":"Sistema de gestão da qualidade"}'::jsonb || COALESCE(title_i18n, '{}'::jsonb),
    text_i18n = '{"pt":"O prestador cria um sistema de gestão da qualidade que inclui políticas, procedimentos e instruções destinados a garantir a conformidade com o EU AI Act."}'::jsonb || COALESCE(text_i18n, '{}'::jsonb)
  WHERE risk_level = 'high'::risk_level AND article_ref = 'Art. 17';
UPDATE ai_act_requirements SET title_i18n = '{"pt":"Supervisão humana atribuída a uma pessoa competente"}'::jsonb || COALESCE(title_i18n, '{}'::jsonb),
    text_i18n = '{"pt":"O responsável pela implantação de um sistema de IA de risco elevado deve atribuir a supervisão humana a pessoas singulares que disponham da competência, formação e autoridade necessárias, bem como do apoio necessário."}'::jsonb || COALESCE(text_i18n, '{}'::jsonb)
  WHERE risk_level = 'high'::risk_level AND article_ref = 'Art. 26 ust. 2';
UPDATE ai_act_requirements SET title_i18n = '{"pt":"Controlo do funcionamento e informação do prestador"}'::jsonb || COALESCE(title_i18n, '{}'::jsonb),
    text_i18n = '{"pt":"O responsável pela implantação deve controlar o funcionamento do sistema com base nas instruções de utilização e informar o prestador e, se for caso disso, a autoridade de fiscalização do mercado de qualquer risco identificado ou incidente grave."}'::jsonb || COALESCE(text_i18n, '{}'::jsonb)
  WHERE risk_level = 'high'::risk_level AND article_ref = 'Art. 26 ust. 5';
UPDATE ai_act_requirements SET title_i18n = '{"pt":"Conservação dos registos gerados automaticamente"}'::jsonb || COALESCE(title_i18n, '{}'::jsonb),
    text_i18n = '{"pt":"O responsável pela implantação deve conservar os registos gerados automaticamente pelo sistema durante um período adequado à finalidade prevista do sistema, de, pelo menos, seis meses, salvo disposição em contrário no direito da União ou nacional aplicável."}'::jsonb || COALESCE(text_i18n, '{}'::jsonb)
  WHERE risk_level = 'high'::risk_level AND article_ref = 'Art. 26 ust. 6';
UPDATE ai_act_requirements SET title_i18n = '{"pt":"Verificação do registo na base de dados da UE"}'::jsonb || COALESCE(title_i18n, '{}'::jsonb),
    text_i18n = '{"pt":"O responsável pela implantação que seja uma autoridade pública deve cumprir as obrigações de registo a que se refere o art. 49.º e, antes de colocar o sistema em serviço, verificar se este está registado na base de dados da UE."}'::jsonb || COALESCE(text_i18n, '{}'::jsonb)
  WHERE risk_level = 'high'::risk_level AND article_ref = 'Art. 26 ust. 8';
UPDATE ai_act_requirements SET title_i18n = '{"pt":"Avaliação de impacto sobre os direitos fundamentais (FRIA)"}'::jsonb || COALESCE(title_i18n, '{}'::jsonb),
    text_i18n = '{"pt":"Antes de implantar um sistema de IA de risco elevado referido no anexo III, ponto 5, alíneas b) ou c) (avaliação da capacidade de endividamento, risco em seguros), ou quando o responsável pela implantação for um organismo de direito público ou uma entidade privada que presta serviços públicos, o responsável pela implantação deve realizar uma avaliação de impacto sobre os direitos fundamentais: descrição dos processos em que o sistema será utilizado, período e frequência de utilização, categorias de pessoas afetadas, riscos de danos para essas pessoas, bem como medidas de supervisão humana e mecanismos de apresentação de queixas."}'::jsonb || COALESCE(text_i18n, '{}'::jsonb)
  WHERE risk_level = 'high'::risk_level AND article_ref = 'Art. 27';
UPDATE ai_act_requirements SET title_i18n = '{"pt":"Avaliação da conformidade"}'::jsonb || COALESCE(title_i18n, '{}'::jsonb),
    text_i18n = '{"pt":"Os sistemas de IA de risco elevado enumerados no anexo III devem ser sujeitos a uma avaliação da conformidade (controlo interno ou com a participação de um organismo notificado) antes da sua colocação no mercado ou colocação em serviço."}'::jsonb || COALESCE(text_i18n, '{}'::jsonb)
  WHERE risk_level = 'high'::risk_level AND article_ref = 'Art. 43';
UPDATE ai_act_requirements SET title_i18n = '{"pt":"Registo na base de dados da UE"}'::jsonb || COALESCE(title_i18n, '{}'::jsonb),
    text_i18n = '{"pt":"Os sistemas de IA de risco elevado devem ser registados na base de dados da UE antes da sua colocação no mercado ou colocação em serviço."}'::jsonb || COALESCE(text_i18n, '{}'::jsonb)
  WHERE risk_level = 'high'::risk_level AND article_ref = 'Art. 49';
UPDATE ai_act_requirements SET title_i18n = '{"pt":"Sistema de gestão de riscos"}'::jsonb || COALESCE(title_i18n, '{}'::jsonb),
    text_i18n = '{"pt":"Um agente de risco elevado exige um sistema de gestão de riscos documentado ao longo de todo o seu ciclo de vida. São exigidas a identificação, a análise e a avaliação dos riscos, bem como a adoção de medidas de gestão de riscos."}'::jsonb || COALESCE(text_i18n, '{}'::jsonb)
  WHERE risk_level = 'high'::risk_level AND article_ref = 'Art. 9';
UPDATE ai_act_requirements SET title_i18n = '{"pt":"Obrigação de divulgar a utilização de IA"}'::jsonb || COALESCE(title_i18n, '{}'::jsonb),
    text_i18n = '{"pt":"Os sistemas destinados a interagir com pessoas singulares devem informar o utilizador, de forma clara, distinguível e atempada, de que está a interagir com um sistema automatizado, salvo se tal for óbvio."}'::jsonb || COALESCE(text_i18n, '{}'::jsonb)
  WHERE risk_level = 'limited'::risk_level AND article_ref = 'Art. 50 ust. 1';
UPDATE ai_act_requirements SET title_i18n = '{"pt":"Marcação de conteúdos gerados por IA"}'::jsonb || COALESCE(title_i18n, '{}'::jsonb),
    text_i18n = '{"pt":"Os conteúdos de texto, áudio e vídeo gerados por IA devem ser marcados num formato legível por máquina como gerados artificialmente."}'::jsonb || COALESCE(text_i18n, '{}'::jsonb)
  WHERE risk_level = 'limited'::risk_level AND article_ref = 'Art. 50 ust. 4';
UPDATE ai_act_requirements SET title_i18n = '{"pt":"Códigos de conduta voluntários"}'::jsonb || COALESCE(title_i18n, '{}'::jsonb),
    text_i18n = '{"pt":"Não se aplicam requisitos legais obrigatórios aos sistemas de risco mínimo. Recomenda-se a aplicação voluntária de códigos de conduta e dos princípios gerais de uma IA de confiança (transparência, equidade, segurança)."}'::jsonb || COALESCE(text_i18n, '{}'::jsonb)
  WHERE risk_level = 'minimal'::risk_level AND article_ref = 'Preambuła 46';
UPDATE ai_act_requirements SET title_i18n = '{"pt":"Proibição absoluta"}'::jsonb || COALESCE(title_i18n, '{}'::jsonb),
    text_i18n = '{"pt":"As práticas de IA enumeradas no art. 5.º são estritamente proibidas na UE. Deve verificar-se que o sistema não se enquadra em nenhuma das categorias proibidas (manipulação subliminar, classificação social, identificação biométrica em tempo real)."}'::jsonb || COALESCE(text_i18n, '{}'::jsonb)
  WHERE risk_level = 'unacceptable'::risk_level AND article_ref = 'Art. 5';

-- ── app_settings ──────────────────────────────────────────────────────────
UPDATE app_settings SET label_i18n = '{"pt":"Limiar de alerta predefinido"}'::jsonb || COALESCE(label_i18n, '{}'::jsonb),
    description_i18n = '{"pt":"Limiar de alerta de custos para novos agentes (0 = desativado)."}'::jsonb || COALESCE(description_i18n, '{}'::jsonb),
    unit_i18n = '{"pt":"EUR"}'::jsonb || COALESCE(unit_i18n, '{}'::jsonb)
  WHERE key = 'budget.default_alert_threshold_eur';
UPDATE app_settings SET label_i18n = '{"pt":"Orçamento mensal predefinido"}'::jsonb || COALESCE(label_i18n, '{}'::jsonb),
    description_i18n = '{"pt":"Orçamento atribuído a novos agentes (0 = sem limite)."}'::jsonb || COALESCE(description_i18n, '{}'::jsonb),
    unit_i18n = '{"pt":"EUR"}'::jsonb || COALESCE(unit_i18n, '{}'::jsonb)
  WHERE key = 'budget.default_monthly_eur';
UPDATE app_settings SET label_i18n = '{"pt":"Prazos das lacunas de conformidade (dias)"}'::jsonb || COALESCE(label_i18n, '{}'::jsonb),
    description_i18n = '{"pt":"Número de dias para corrigir cada lacuna de conformidade de risco elevado (chave = campo de controlo)."}'::jsonb || COALESCE(description_i18n, '{}'::jsonb),
    unit_i18n = '{"pt":"dias"}'::jsonb || COALESCE(unit_i18n, '{}'::jsonb)
  WHERE key = 'compliance.deadline_days';
UPDATE app_settings SET label_i18n = '{"pt":"Relatório da organização — máx. tokens"}'::jsonb || COALESCE(label_i18n, '{}'::jsonb),
    description_i18n = '{"pt":"Limite de tokens para a narrativa do relatório da organização."}'::jsonb || COALESCE(description_i18n, '{}'::jsonb),
    unit_i18n = '{"pt":"tokens"}'::jsonb || COALESCE(unit_i18n, '{}'::jsonb)
  WHERE key = 'compliance.enterprise_report_max_tokens';
UPDATE app_settings SET label_i18n = '{"pt":"Relatório do agente — máx. tokens"}'::jsonb || COALESCE(label_i18n, '{}'::jsonb),
    description_i18n = '{"pt":"Limite de tokens para a narrativa do relatório de conformidade do agente."}'::jsonb || COALESCE(description_i18n, '{}'::jsonb),
    unit_i18n = '{"pt":"tokens"}'::jsonb || COALESCE(unit_i18n, '{}'::jsonb)
  WHERE key = 'compliance.report_max_tokens';
UPDATE app_settings SET label_i18n = '{"pt":"Idioma predefinido"}'::jsonb || COALESCE(label_i18n, '{}'::jsonb),
    description_i18n = '{"pt":"Idioma da interface, dos relatórios e das mensagens para os utilizadores que não escolheram o seu. Códigos: pl, en, de, it, es, fr, ro, ru, sl, hr, pt."}'::jsonb || COALESCE(description_i18n, '{}'::jsonb)
  WHERE key = 'i18n.default_locale';
UPDATE app_settings SET label_i18n = '{"pt":"Atualização das políticas"}'::jsonb || COALESCE(label_i18n, '{}'::jsonb),
    description_i18n = '{"pt":"Frequência (em segundos) com que o gateway recarrega as regras das políticas a partir da base de dados."}'::jsonb || COALESCE(description_i18n, '{}'::jsonb),
    unit_i18n = '{"pt":"segundos"}'::jsonb || COALESCE(unit_i18n, '{}'::jsonb)
  WHERE key = 'intervals.policy_refresh_seconds';
UPDATE app_settings SET label_i18n = '{"pt":"Monitor de TTL da supervisão"}'::jsonb || COALESCE(label_i18n, '{}'::jsonb),
    description_i18n = '{"pt":"Frequência (em segundos) com que o monitor escala as tarefas de supervisão em atraso."}'::jsonb || COALESCE(description_i18n, '{}'::jsonb),
    unit_i18n = '{"pt":"segundos"}'::jsonb || COALESCE(unit_i18n, '{}'::jsonb)
  WHERE key = 'intervals.ttl_monitor_seconds';
UPDATE app_settings SET label_i18n = '{"pt":"Modelo classificador do AI Act"}'::jsonb || COALESCE(label_i18n, '{}'::jsonb),
    description_i18n = '{"pt":"Modelo utilizado para avaliar o nível de risco de um agente."}'::jsonb || COALESCE(description_i18n, '{}'::jsonb)
  WHERE key = 'models.classifier_model';
UPDATE app_settings SET label_i18n = '{"pt":"Modelo predefinido do agente"}'::jsonb || COALESCE(label_i18n, '{}'::jsonb),
    description_i18n = '{"pt":"Modelo atribuído aos agentes recém-registados."}'::jsonb || COALESCE(description_i18n, '{}'::jsonb)
  WHERE key = 'models.default_agent_model';
UPDATE app_settings SET label_i18n = '{"pt":"Limite de tokens predefinido"}'::jsonb || COALESCE(label_i18n, '{}'::jsonb),
    description_i18n = '{"pt":"Limite de tokens de saída quando o cliente não o especifica."}'::jsonb || COALESCE(description_i18n, '{}'::jsonb),
    unit_i18n = '{"pt":"tokens"}'::jsonb || COALESCE(unit_i18n, '{}'::jsonb)
  WHERE key = 'models.default_max_tokens';
UPDATE app_settings SET label_i18n = '{"pt":"Temperatura predefinida"}'::jsonb || COALESCE(label_i18n, '{}'::jsonb),
    description_i18n = '{"pt":"Temperatura do LLM quando o cliente não a especifica."}'::jsonb || COALESCE(description_i18n, '{}'::jsonb),
    unit_i18n = '{"pt":"0–2"}'::jsonb || COALESCE(unit_i18n, '{}'::jsonb)
  WHERE key = 'models.default_temperature';
UPDATE app_settings SET label_i18n = '{"pt":"Histórico de supervisão — limite de linhas"}'::jsonb || COALESCE(label_i18n, '{}'::jsonb),
    description_i18n = '{"pt":"Limite rígido do número de itens do histórico de supervisão."}'::jsonb || COALESCE(description_i18n, '{}'::jsonb),
    unit_i18n = '{"pt":"linhas"}'::jsonb || COALESCE(unit_i18n, '{}'::jsonb)
  WHERE key = 'oversight.history_limit';
UPDATE app_settings SET label_i18n = '{"pt":"Histórico de supervisão — máx. dias"}'::jsonb || COALESCE(label_i18n, '{}'::jsonb),
    description_i18n = '{"pt":"Intervalo máximo de dias para GET /oversight/history."}'::jsonb || COALESCE(description_i18n, '{}'::jsonb),
    unit_i18n = '{"pt":"dias"}'::jsonb || COALESCE(unit_i18n, '{}'::jsonb)
  WHERE key = 'oversight.history_max_days';
UPDATE app_settings SET label_i18n = '{"pt":"Tempo mín. de revisão"}'::jsonb || COALESCE(label_i18n, '{}'::jsonb),
    description_i18n = '{"pt":"Uma revisão de supervisão mais curta do que este número de segundos é assinalada como aprovação automática (rubber-stamping)."}'::jsonb || COALESCE(description_i18n, '{}'::jsonb),
    unit_i18n = '{"pt":"segundos"}'::jsonb || COALESCE(unit_i18n, '{}'::jsonb)
  WHERE key = 'oversight.min_review_seconds';
UPDATE app_settings SET label_i18n = '{"pt":"TTL da tarefa de supervisão"}'::jsonb || COALESCE(label_i18n, '{}'::jsonb),
    description_i18n = '{"pt":"Tempo até uma tarefa na fila de supervisão ser escalada."}'::jsonb || COALESCE(description_i18n, '{}'::jsonb),
    unit_i18n = '{"pt":"segundos"}'::jsonb || COALESCE(unit_i18n, '{}'::jsonb)
  WHERE key = 'oversight.ttl_seconds';
UPDATE app_settings SET label_i18n = '{"pt":"Auditoria — limite predefinido"}'::jsonb || COALESCE(label_i18n, '{}'::jsonb),
    description_i18n = '{"pt":"Número predefinido de entradas em GET /audit."}'::jsonb || COALESCE(description_i18n, '{}'::jsonb),
    unit_i18n = '{"pt":"linhas"}'::jsonb || COALESCE(unit_i18n, '{}'::jsonb)
  WHERE key = 'pagination.audit_default_limit';
UPDATE app_settings SET label_i18n = '{"pt":"Auditoria — limite máx."}'::jsonb || COALESCE(label_i18n, '{}'::jsonb),
    description_i18n = '{"pt":"Número máximo de entradas numa única consulta de auditoria."}'::jsonb || COALESCE(description_i18n, '{}'::jsonb),
    unit_i18n = '{"pt":"linhas"}'::jsonb || COALESCE(unit_i18n, '{}'::jsonb)
  WHERE key = 'pagination.audit_max_limit';
UPDATE app_settings SET label_i18n = '{"pt":"Painel — bloqueios recentes"}'::jsonb || COALESCE(label_i18n, '{}'::jsonb),
    description_i18n = '{"pt":"Número de bloqueios recentes apresentados nos alertas do painel."}'::jsonb || COALESCE(description_i18n, '{}'::jsonb),
    unit_i18n = '{"pt":"itens"}'::jsonb || COALESCE(unit_i18n, '{}'::jsonb)
  WHERE key = 'pagination.dashboard_recent_blocks';
UPDATE app_settings SET label_i18n = '{"pt":"Painel — agentes mais ativos"}'::jsonb || COALESCE(label_i18n, '{}'::jsonb),
    description_i18n = '{"pt":"Número de agentes mais ativos apresentados no painel."}'::jsonb || COALESCE(description_i18n, '{}'::jsonb),
    unit_i18n = '{"pt":"itens"}'::jsonb || COALESCE(unit_i18n, '{}'::jsonb)
  WHERE key = 'pagination.dashboard_top_agents';
UPDATE app_settings SET label_i18n = '{"pt":"Janela predefinida (dias)"}'::jsonb || COALESCE(label_i18n, '{}'::jsonb),
    description_i18n = '{"pt":"Intervalo predefinido de dias para o registo de auditoria e o painel."}'::jsonb || COALESCE(description_i18n, '{}'::jsonb),
    unit_i18n = '{"pt":"dias"}'::jsonb || COALESCE(unit_i18n, '{}'::jsonb)
  WHERE key = 'pagination.default_window_days';
UPDATE app_settings SET label_i18n = '{"pt":"Estatísticas do agente — dias predefinidos"}'::jsonb || COALESCE(label_i18n, '{}'::jsonb),
    description_i18n = '{"pt":"Intervalo predefinido para GET /agents/{id}/stats."}'::jsonb || COALESCE(description_i18n, '{}'::jsonb),
    unit_i18n = '{"pt":"dias"}'::jsonb || COALESCE(unit_i18n, '{}'::jsonb)
  WHERE key = 'pagination.stats_default_days';
UPDATE app_settings SET label_i18n = '{"pt":"Estatísticas do agente — máx. dias"}'::jsonb || COALESCE(label_i18n, '{}'::jsonb),
    description_i18n = '{"pt":"Intervalo máximo para as estatísticas do agente."}'::jsonb || COALESCE(description_i18n, '{}'::jsonb),
    unit_i18n = '{"pt":"dias"}'::jsonb || COALESCE(unit_i18n, '{}'::jsonb)
  WHERE key = 'pagination.stats_max_days';
UPDATE app_settings SET label_i18n = '{"pt":"Cronologia — horas predefinidas"}'::jsonb || COALESCE(label_i18n, '{}'::jsonb),
    description_i18n = '{"pt":"Janela predefinida do gráfico de cronologia."}'::jsonb || COALESCE(description_i18n, '{}'::jsonb),
    unit_i18n = '{"pt":"horas"}'::jsonb || COALESCE(unit_i18n, '{}'::jsonb)
  WHERE key = 'pagination.timeline_default_hours';
UPDATE app_settings SET label_i18n = '{"pt":"Cronologia — máx. horas"}'::jsonb || COALESCE(label_i18n, '{}'::jsonb),
    description_i18n = '{"pt":"Intervalo máximo do gráfico de cronologia."}'::jsonb || COALESCE(description_i18n, '{}'::jsonb),
    unit_i18n = '{"pt":"horas"}'::jsonb || COALESCE(unit_i18n, '{}'::jsonb)
  WHERE key = 'pagination.timeline_max_hours';
UPDATE app_settings SET label_i18n = '{"pt":"Tarifa predefinida (USD/1k tok.)"}'::jsonb || COALESCE(label_i18n, '{}'::jsonb),
    description_i18n = '{"pt":"Tarifa [entrada, saída] para modelos que não constam do mapa."}'::jsonb || COALESCE(description_i18n, '{}'::jsonb),
    unit_i18n = '{"pt":"USD/1k"}'::jsonb || COALESCE(unit_i18n, '{}'::jsonb)
  WHERE key = 'pricing.default_rate';
UPDATE app_settings SET label_i18n = '{"pt":"Tarifas dos modelos (USD/1k tok.)"}'::jsonb || COALESCE(label_i18n, '{}'::jsonb),
    description_i18n = '{"pt":"Mapa modelo → [entrada, saída] em USD por 1000 tokens. Os modelos que não constam da lista utilizam a tarifa predefinida."}'::jsonb || COALESCE(description_i18n, '{}'::jsonb),
    unit_i18n = '{"pt":"USD/1k"}'::jsonb || COALESCE(unit_i18n, '{}'::jsonb)
  WHERE key = 'pricing.model_rates';
UPDATE app_settings SET label_i18n = '{"pt":"Taxa USD→EUR"}'::jsonb || COALESCE(label_i18n, '{}'::jsonb),
    description_i18n = '{"pt":"Multiplicador para converter os custos dos modelos de USD para EUR."}'::jsonb || COALESCE(description_i18n, '{}'::jsonb),
    unit_i18n = '{"pt":"multiplicador"}'::jsonb || COALESCE(unit_i18n, '{}'::jsonb)
  WHERE key = 'pricing.usd_to_eur';
UPDATE app_settings SET label_i18n = '{"pt":"Validade do token de acesso"}'::jsonb || COALESCE(label_i18n, '{}'::jsonb),
    description_i18n = '{"pt":"Tempo de vida do token de acesso JWT."}'::jsonb || COALESCE(description_i18n, '{}'::jsonb),
    unit_i18n = '{"pt":"minutos"}'::jsonb || COALESCE(unit_i18n, '{}'::jsonb)
  WHERE key = 'security.access_token_expire_minutes';
UPDATE app_settings SET label_i18n = '{"pt":"Rondas bcrypt"}'::jsonb || COALESCE(label_i18n, '{}'::jsonb),
    description_i18n = '{"pt":"Custo do hashing das palavras-passe (mais alto = mais lento, mais seguro)."}'::jsonb || COALESCE(description_i18n, '{}'::jsonb),
    unit_i18n = '{"pt":"rondas"}'::jsonb || COALESCE(unit_i18n, '{}'::jsonb)
  WHERE key = 'security.bcrypt_rounds';
UPDATE app_settings SET label_i18n = '{"pt":"Limiar de confiança PII"}'::jsonb || COALESCE(label_i18n, '{}'::jsonb),
    description_i18n = '{"pt":"Nível mínimo de confiança do Presidio para que uma deteção de PII seja aceite."}'::jsonb || COALESCE(description_i18n, '{}'::jsonb),
    unit_i18n = '{"pt":"0–1"}'::jsonb || COALESCE(unit_i18n, '{}'::jsonb)
  WHERE key = 'security.pii_confidence_threshold';
UPDATE app_settings SET label_i18n = '{"pt":"Validade do token de atualização"}'::jsonb || COALESCE(label_i18n, '{}'::jsonb),
    description_i18n = '{"pt":"Tempo de vida do token de atualização."}'::jsonb || COALESCE(description_i18n, '{}'::jsonb),
    unit_i18n = '{"pt":"dias"}'::jsonb || COALESCE(unit_i18n, '{}'::jsonb)
  WHERE key = 'security.refresh_token_expire_days';

-- ── providers ─────────────────────────────────────────────────────────────
UPDATE providers SET notes_i18n = '{"pt":"Fornecedor externo. Exige um DPA. Não utilizar para dados abrangidos pelo segredo profissional de advogado."}'::jsonb || COALESCE(notes_i18n, '{}'::jsonb)
  WHERE name = 'Anthropic Claude (Cloud)';
UPDATE providers SET notes_i18n = '{"pt":"Modelo local — adequado para dados abrangidos pelo segredo profissional de advogado. Ativar após o arranque do servidor Ollama."}'::jsonb || COALESCE(notes_i18n, '{}'::jsonb)
  WHERE name = 'Bielik On-Prem (Local)';
UPDATE providers SET notes_i18n = '{"pt":"Servidores fora da UE (China). Apenas dados públicos — é proibido o tratamento de dados de clientes."}'::jsonb || COALESCE(notes_i18n, '{}'::jsonb)
  WHERE name = 'DeepSeek (Cloud)';
UPDATE providers SET notes_i18n = '{"pt":"Fornecedor externo com EU Data Boundary. Exige um DPA. Não utilizar para dados protegidos por segredo profissional."}'::jsonb || COALESCE(notes_i18n, '{}'::jsonb)
  WHERE name = 'Google Gemini (Cloud)';
UPDATE providers SET notes_i18n = '{"pt":"Fornecedor externo. Exige um DPA Enterprise. Não utilizar para dados confidenciais."}'::jsonb || COALESCE(notes_i18n, '{}'::jsonb)
  WHERE name = 'OpenAI (Cloud)';
