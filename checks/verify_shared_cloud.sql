-- Run after the Music Rating migrations in a disposable Supabase-compatible database.
begin;
insert into auth.users (id) values
    ('aaaaaaaa-0000-0000-0000-000000000001'),
    ('bbbbbbbb-0000-0000-0000-000000000002'),
    ('cccccccc-0000-0000-0000-000000000003');
insert into public.music_rating_members (user_id, display_name) values
    ('aaaaaaaa-0000-0000-0000-000000000001', 'Georgy'),
    ('bbbbbbbb-0000-0000-0000-000000000002', 'Volodya');

update auth.users set raw_user_meta_data = '{"display_name":" Georgy New "}'
    where id = 'aaaaaaaa-0000-0000-0000-000000000001';
update auth.users set raw_user_meta_data = '{"display_name":42}'
    where id = 'bbbbbbbb-0000-0000-0000-000000000002';
update auth.users set raw_user_meta_data = '{"display_name":"Georgy New"}'
    where id = 'cccccccc-0000-0000-0000-000000000003';

create policy test_other_storage_policy on storage.objects for all to anon, authenticated
    using (true) with check (true);
insert into storage.buckets (id, name, public) values ('other-bucket', 'other-bucket', true);
insert into storage.objects (bucket_id, name) values ('other-bucket', 'ordinary-object');

set local role authenticated;
select set_config('request.jwt.claim.sub', 'aaaaaaaa-0000-0000-0000-000000000001', true);
select public.music_rating_upload('[{"kind":"artist","item_id":"private","snapshot_hash":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","payload":{"name":"Private artist"}}]');
insert into storage.objects (bucket_id, name) values ('music-rating-shared-artwork', repeat('a', 64));
select public.music_rating_shared_upload('[{"kind":"album","item_id":"a","payload":{"title":"Album"}},
    {"kind":"rating","item_id":"a:aaaaaaaa-0000-0000-0000-000000000001","payload":{"album_id":"a","rater_key":"aaaaaaaa-0000-0000-0000-000000000001","name":"Georgy","scores":{"track":8}}}]');

select set_config('request.jwt.claim.sub', 'bbbbbbbb-0000-0000-0000-000000000002', true);
select public.music_rating_shared_upload('[{"kind":"rating","item_id":"a:bbbbbbbb-0000-0000-0000-000000000002","payload":{"album_id":"a","rater_key":"bbbbbbbb-0000-0000-0000-000000000002","name":"Volodya","scores":{"track":7}}}]');
-- One operator can enter or update a rating on behalf of another member.
select public.music_rating_shared_upload('[{"kind":"rating","item_id":"a:aaaaaaaa-0000-0000-0000-000000000001","payload":{"album_id":"a","rater_key":"aaaaaaaa-0000-0000-0000-000000000001","name":"Georgy","scores":{"track":9}}}]');
select public.music_rating_shared_upload('[{"kind":"rating","item_id":"a:aaaaaaaa-0000-0000-0000-000000000001","payload":{"album_id":"a","rater_key":"aaaaaaaa-0000-0000-0000-000000000001","name":"Georgy","scores":{"track":9}}}]');

do $$
declare
    status jsonb := public.music_rating_shared_status(true);
begin
    if status->>'revision' <> '3:' or jsonb_array_length(status->'members') <> 2
        or not (status->'members' @> '[{"id":"aaaaaaaa-0000-0000-0000-000000000001","name":"Georgy New"},
                                      {"id":"bbbbbbbb-0000-0000-0000-000000000002","name":"Volodya"}]')
        or jsonb_array_length(status->'shared') <> 3 or status->'personal' <> '[]'::jsonb
        or not (status->'shared' @> '[{"kind":"rating","payload":{"name":"Georgy","scores":{"track":9}}}]')
        or not (status->'shared' @> '[{"kind":"rating","payload":{"name":"Volodya","scores":{"track":7}}}]')
        or not exists (select 1 from storage.objects where bucket_id = 'music-rating-shared-artwork') then
        raise exception 'Column merge, idempotence, or read isolation failed';
    end if;
    if public.music_rating_shared_status(false) ? 'shared' then
        raise exception 'Polling returns the whole library';
    end if;
end;
$$;

select set_config('request.jwt.claim.sub', 'aaaaaaaa-0000-0000-0000-000000000001', true);
do $$ begin
    if jsonb_array_length(public.music_rating_shared_status(true)->'personal') <> 1 then
        raise exception 'An existing private backup is inaccessible to its owner';
    end if;
end $$;

select set_config('request.jwt.claim.sub', 'cccccccc-0000-0000-0000-000000000003', true);
do $$ begin
    begin
        perform public.music_rating_shared_status(true);
        raise exception 'Non-member can read the shared library';
    exception when sqlstate 'PT403' then null;
    end;
    begin
        perform public.music_rating_shared_upload('[]');
        raise exception 'Non-member can write the shared library';
    exception when sqlstate 'PT403' then null;
    end;
    if exists (select 1 from storage.objects where bucket_id = 'music-rating-shared-artwork') then
        raise exception 'Non-member can read shared artwork';
    end if;
end $$;

set local role anon;
select set_config('request.jwt.claim.sub', '', true);
do $$ begin
    if exists (select 1 from storage.objects where bucket_id = 'music-rating-shared-artwork')
        or not exists (select 1 from storage.objects where bucket_id = 'other-bucket') then
        raise exception 'Shared restrictions leaked to another bucket or exposed artwork';
    end if;
    begin
        perform public.music_rating_shared_status(true);
        raise exception 'Anonymous user can run the status function';
    exception when insufficient_privilege then null;
    end;
end $$;
rollback;
