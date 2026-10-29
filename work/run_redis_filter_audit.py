import json,os,subprocess,sys
from pathlib import Path
selected={
 'calendar':'test_calendar_cache_hit_has_zero_mysql_access',
 'capital':'test_repeat_hot_cold_revision_old_response_and_missing_fields',
 'financial':'test_hot_cold_revision_old_and_repair',
 'holder':'test_hot_cold_revision_old_observation_and_field_repair',
 'index':'test_cold_hot_revision_late_old_unavailable_and_recovery',
 'index_price':'test_hot_cold_duplicate_revision_late_response_no_business_dml',
 'industry':'test_hot_cold_same_content_revisions_removal_stale_and_repair',
 'intraday':'test_hot_cold_no_dml_revision_and_late_old_response',
 'kaipanla_products':'test_each_source_no_dml_revision_old_response_and_ack_replay',
 'listing':'test_hot_cold_no_dml_revision_stale_and_redis_loss',
 'listing_status':'test_hot_cold_duplicate_revision_stale_and_equal_count_sql_corruption',
 'name':'test_hot_cold_duplicate_revision_stale_and_same_count_wrong_sql',
 'news':'test_fingerprint_hit_skips_sql_and_miss_confirms_then_deletes_queue',
 'repurchase':'test_hot_cold_revision_stale_and_missing_field_repair',
 'rule':'test_hot_cold_zero_dml_metadata_revision_late_old_and_corruption',
 'st':'test_hot_cold_duplicate_revision_stale_and_same_count_wrong_sql',
 'suspension':'test_insert_repeat_cache_hit_and_cache_loss_have_no_duplicate_dml',
 'tdx_performance':'test_hot_cold_repeat_revision_old_response_and_replay',
 'tdx_shareholder_changes':'test_duplicate_facts_query_filters_hot_cold_revision_stale_replay',
 'tdx_unlocks':'test_parent_shared_group_query_hot_cold_revision_stale_replay',
 'tdx_unlock_industries':'test_hot_cold_repeat_revision_old_basis_wrong_set_and_old_month_retention',
 'theme':'test_detail_hot_cold_repeat_success_queue_cleanup_and_official_query',
 'ths_capital':'test_roundtrip_hot_cold_zero_dml_revision_old_replay_and_required_field_repair',
 'ths_stock':'test_ths_source_to_query_cold_hot_repair_replay_and_cross_source_old_version',
 'yuanhang':'test_hot_fingerprint_is_sql_free_and_cold_duplicate_or_stale_cleans_message',
 'yuanhang_limits':'test_pool_real_archive_formal_query_hot_cold_repeat_zero_dml',
}
nodes=[f'tests/integration/test_{f}_archive.py::{name}' for f,name in selected.items()]
nodes += ['tests/integration/test_news_archive.py::'+n for n in ['test_mixed_page_only_sends_cache_misses_to_sql','test_cache_bounds_expiry_and_old_sql_version_not_cached','test_transaction_rollback_cannot_publish_fingerprint','test_fingerprint_cache_failure_after_commit_preserves_queue']]
Path('docs/evidence/redis-filter-audit-tests-2026-10-29.json').write_text(json.dumps(nodes,indent=2)+'\n',encoding='utf-8')
env={**os.environ,'EMPIRE_INTEGRATION':'1','PYTHONIOENCODING':'utf-8'}
result=subprocess.run([sys.executable,'-m','pytest',*nodes,'-q','--tb=short','--basetemp=build/pytest-redis-filter-audit-20261029','--junitxml=build/redis-filter-audit-20261029.xml'],env=env)
sys.exit(result.returncode)
