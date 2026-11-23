begin;

-- Auth metadata supplies the label. Membership continues to grant access.
create or replace function public.music_rating_shared_status(p_download boolean default false) returns jsonb
    language plpgsql stable security definer set search_path = '' as $$
declare
    caller uuid := auth.uid();
    result jsonb;
begin
    if not exists (select 1 from public.music_rating_members where user_id = caller) then
        raise exception using errcode = 'PT403', message = 'MUSIC_RATING_MEMBERSHIP_REQUIRED';
    end if;

    select jsonb_build_object(
        'revision', revision::text || ':' || coalesce((
            select max(updated_at)::text from public.music_rating_library where owner_id = caller
        ), ''),
        'members', (
            select coalesce(jsonb_agg(jsonb_build_object(
                'id', user_id, 'name', display_name) order by lower(display_name), user_id), '[]'::jsonb)
            from (
                select member.user_id,
                    case when jsonb_typeof(account.raw_user_meta_data->'display_name') = 'string'
                        and char_length(btrim(account.raw_user_meta_data->>'display_name')) between 1 and 80
                        and (account.raw_user_meta_data->>'display_name') !~ '[[:cntrl:]]'
                    then btrim(account.raw_user_meta_data->>'display_name')
                    else btrim(member.display_name)
                    end as display_name
                from public.music_rating_members member
                join auth.users account on account.id = member.user_id
            ) directory
        ),
        'has_data', exists (select 1 from public.music_rating_shared)
            or exists (select 1 from public.music_rating_library where owner_id = caller)
    ) into result from public.music_rating_shared_revision;

    if p_download then
        result := result || jsonb_build_object(
            'shared', (select coalesce(jsonb_agg(to_jsonb(row) order by kind, item_id), '[]'::jsonb)
                from public.music_rating_shared row),
            'personal', (select coalesce(jsonb_agg(jsonb_build_object(
                'kind', kind, 'item_id', item_id, 'payload', payload) order by kind, item_id), '[]'::jsonb)
                from public.music_rating_library where owner_id = caller)
        );
    end if;
    return result;
end;
$$;

commit;
