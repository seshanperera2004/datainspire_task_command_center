"""
Tasks — the core task management page.
President: create/edit/delete tasks, approve/return submissions.
EXCO: view assigned tasks, update progress, submit for review, comment, upload files.
"""

import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.components.page_init import init_page
init_page("Tasks", "✅")

import streamlit as st
from datetime import date, timedelta
from app.services import task_service as ts
from app.services.admin_service import list_departments, list_users
from app.components.theme import priority_badge_html, status_badge_html
from app.components.widgets import section_label, days_until
from app.utils.file_storage import save_file, read_file_bytes

user = st.session_state["user"]
is_president = user["role_name"] == "President"

st.title("✅ Tasks")

# Deep-link support: ?task_id=N to jump straight to a task's detail view
query_task_id = st.query_params.get("task_id")

# Track selected task in session state
if "selected_task_id" not in st.session_state:
    st.session_state["selected_task_id"] = None

# If task_id is in query params, use it
if query_task_id:
    st.session_state["selected_task_id"] = int(query_task_id)

# Track upload state to prevent double uploads
if "upload_done" not in st.session_state:
    st.session_state["upload_done"] = False

# =====================================================================
# SHOW DETAIL VIEW if a task is selected
# =====================================================================
if st.session_state["selected_task_id"]:
    task_id = st.session_state["selected_task_id"]

    if st.button("← Back to Task List"):
        st.session_state["selected_task_id"] = None
        st.session_state["upload_done"] = False
        st.query_params.clear()
        st.rerun()

    task = ts.get_task(task_id)
    if not task:
        st.error("Task not found.")
        st.session_state["selected_task_id"] = None
        st.rerun()

    overdue = ts.is_overdue(task)
    d_left = days_until(task["deadline"])

    st.markdown(f"#### {task['title']}")
    st.caption(f"{task['task_code']} · {task['department_name']}")

    badge_row = f"{priority_badge_html(task['priority'])} {status_badge_html(task['status'])}"
    if overdue:
        badge_row += ' <span class="dc-badge" style="--badge-color:#E63946">⚠ Overdue</span>'
    st.markdown(badge_row, unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    info_col1, info_col2, info_col3 = st.columns(3)
    info_col1.metric("Assigned To", task["assigned_to_name"] or "Unassigned")
    info_col2.metric("Deadline", task["deadline"], delta=f"{d_left} days left" if d_left >= 0 else f"{abs(d_left)} days overdue")
    info_col3.metric("Created By", task["created_by_name"])

    st.markdown("**Description**")
    st.write(task["description"] or "_No description provided._")

    st.divider()

    # --------------------------------------------------------
    # WORKFLOW ACTIONS
    # --------------------------------------------------------
    section_label("Workflow Actions")
    can_act_exco = (not is_president) and task["assigned_to"] == user["user_id"]

    if is_president:
        ac1, ac2, ac3 = st.columns(3)
        with ac1:
            if task["status"] == ts.STATUS_SUBMITTED:
                if st.button("✅ Approve Task", type="primary", width='stretch'):
                    ts.change_status(task["task_id"], ts.STATUS_APPROVED, user["user_id"], "Approved by President", is_president=True)
                    st.success("Task approved!")
                    st.rerun()
        with ac2:
            if task["status"] == ts.STATUS_SUBMITTED:
                with st.popover("↩️ Return for Revision", width='stretch'):
                    note = st.text_area("Feedback for the member", key="return_note")
                    if st.button("Confirm Return", key="confirm_return"):
                        ts.change_status(task["task_id"], ts.STATUS_RETURNED, user["user_id"], note, is_president=True)
                        st.success("Task returned for revision.")
                        st.rerun()
        with ac3:
            with st.popover("🗑️ Delete Task", width='stretch'):
                st.warning("This will remove the task from active lists.")
                if st.button("Confirm Delete", key="confirm_delete"):
                    ts.delete_task(task["task_id"], user["user_id"])
                    st.success("Task deleted.")
                    st.session_state["selected_task_id"] = None
                    st.query_params.clear()
                    st.rerun()

        with st.expander("✏️ Edit Task Details"):
            depts_all2 = list_departments()
            dept_map = {d["department_name"]: d["department_id"] for d in depts_all2}
            current_dept_name = task["department_name"]

            members2 = list_users(department_id=task["department_id"])
            assignee_map = {"— Unassigned —": None}
            assignee_map.update({m["full_name"]: m["user_id"] for m in members2})
            current_assignee = task["assigned_to_name"] or "— Unassigned —"
            if current_assignee not in assignee_map:
                assignee_map[current_assignee] = task["assigned_to"]

            with st.form("edit_task_form"):
                new_title = st.text_input("Title", value=task["title"])
                new_desc = st.text_area("Description", value=task["description"] or "")
                new_dept = st.selectbox("Department", list(dept_map.keys()), index=list(dept_map.keys()).index(current_dept_name) if current_dept_name in dept_map else 0)
                new_priority = st.selectbox("Priority", ts.PRIORITIES, index=ts.PRIORITIES.index(task["priority"]))
                new_assignee = st.selectbox("Assigned To", list(assignee_map.keys()), index=list(assignee_map.keys()).index(current_assignee))
                new_deadline = st.date_input("Deadline", value=date.fromisoformat(task["deadline"][:10]))

                if st.form_submit_button("Save Changes", type="primary"):
                    ts.update_task_details(
                        task["task_id"], user["user_id"],
                        title=new_title, description=new_desc,
                        department_id=dept_map[new_dept],
                        assigned_to=assignee_map[new_assignee],
                        priority=new_priority,
                        deadline=new_deadline.isoformat(),
                    )
                    st.success("Task updated.")
                    st.rerun()

    elif can_act_exco:
        allowed = ts.EXCO_ALLOWED_STATUS_TRANSITIONS.get(task["status"], [])
        if allowed:
            cols = st.columns(len(allowed))
            for i, next_status in enumerate(allowed):
                with cols[i]:
                    label_map = {
                        ts.STATUS_IN_PROGRESS: "▶️ Mark In Progress",
                        ts.STATUS_SUBMITTED: "📤 Submit for Review",
                    }
                    if st.button(label_map.get(next_status, next_status), width='stretch', type="primary"):
                        ok, msg = ts.change_status(task["task_id"], next_status, user["user_id"], is_president=False)
                        if ok:
                            st.success(msg)
                            st.rerun()
                        else:
                            st.error(msg)
        else:
            st.info(f"No further action available — current status: **{task['status']}**.")

        if task["status"] == ts.STATUS_RETURNED and task["approval_notes"]:
            st.warning(f"**President's feedback:** {task['approval_notes']}")
    else:
        st.caption("You can view this task but it is not assigned to you.")

    st.divider()

    # --------------------------------------------------------
    # ATTACHMENTS
    # --------------------------------------------------------
    section_label("📎 Attachments")
    can_upload = is_president or can_act_exco

    if can_upload:
        # Reset upload_done when a new file is selected
        uploaded = st.file_uploader(
            "Upload supporting file (PDF, Word, image, PowerPoint, etc.)",
            key=f"uploader_{task['task_id']}",
        )

        if uploaded is not None and not st.session_state["upload_done"]:
            if st.button("Confirm Upload"):
                ok, msg, info = save_file(task["task_id"], uploaded)
                if ok:
                    ts.add_attachment(
                        task["task_id"], user["user_id"],
                        info["file_name"], info["stored_path"],
                        info["file_type"], info["file_size_kb"],
                    )
                    st.session_state["upload_done"] = True
                    st.success(msg)
                    st.rerun()
                else:
                    st.error(msg)
        elif st.session_state["upload_done"]:
            st.success("File uploaded successfully! Select another file to upload again.")
            if st.button("Upload another file"):
                st.session_state["upload_done"] = False
                st.rerun()

    attachments = ts.get_attachments(task["task_id"])
    if attachments:
        for att in attachments:
            fbytes = read_file_bytes(att["stored_path"])
            cols = st.columns([3, 1, 1])
            cols[0].write(f"📄 **{att['file_name']}** ({att['file_size_kb']} KB)")
            cols[1].caption(f"by {att['uploaded_by_name']}")
            if fbytes:
                cols[2].download_button("Download", fbytes, file_name=att["file_name"], key=f"dl_{att['attachment_id']}")
    else:
        st.caption("No files uploaded yet.")

    st.divider()

    # --------------------------------------------------------
    # COMMENTS / DISCUSSION
    # --------------------------------------------------------
    section_label("💬 Discussion")
    comments = ts.get_comments(task["task_id"])
    if comments:
        for c in comments:
            st.markdown(
                f"""
                <div class="dc-comment">
                    <div class="dc-comment-meta">
                        <span class="dc-comment-author">{c['full_name']}</span>
                        <span style="color:var(--text-muted);"> ({c['role_name']})</span>
                        &nbsp;·&nbsp; {c['created_at']}
                    </div>
                    <div>{c['message']}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
    else:
        st.caption("No comments yet — start the discussion below.")

    with st.form(f"comment_form_{task['task_id']}", clear_on_submit=True):
        new_comment = st.text_area("Add a comment or update", label_visibility="collapsed", placeholder="Share a progress update, instruction, or clarification...")
        if st.form_submit_button("Post Comment"):
            if new_comment.strip():
                ts.add_comment(task["task_id"], user["user_id"], new_comment)
                st.rerun()

    st.divider()

    # --------------------------------------------------------
    # STATUS HISTORY
    # --------------------------------------------------------
    with st.expander("🕓 Status History / Audit Trail"):
        history = ts.get_status_history(task["task_id"])
        for h in history:
            old = h["old_status"] or "—"
            st.markdown(
                f"**{h['changed_at']}** — {h['full_name']} changed status from *{old}* → **{h['new_status']}**"
                + (f"  \n_Note: {h['note']}_" if h["note"] else "")
            )

# =====================================================================
# TASK LIST VIEW (shown when no task is selected)
# =====================================================================
else:
    if is_president:
        with st.expander("➕ Create New Task", expanded=False):
            depts = list_departments()
            dept_options = {d["department_name"]: d["department_id"] for d in depts}

            with st.form("create_task_form", clear_on_submit=True):
                col1, col2 = st.columns(2)
                with col1:
                    title = st.text_input("Task Title *")
                    dept_name = st.selectbox("Department / Task Group *", list(dept_options.keys()))
                    priority = st.selectbox("Priority *", ts.PRIORITIES, index=1)
                with col2:
                    members = list_users(department_id=dept_options.get(dept_name))
                    assignee_options = {"— Unassigned (whole department) —": None}
                    assignee_options.update({m["full_name"]: m["user_id"] for m in members})
                    assignee_name = st.selectbox("Assign To", list(assignee_options.keys()))
                    deadline = st.date_input("Deadline *", value=date.today() + timedelta(days=7))

                description = st.text_area("Description")
                submitted = st.form_submit_button("Create Task", type="primary", width='stretch')

                if submitted:
                    if not title.strip():
                        st.error("Task title is required.")
                    else:
                        success, msg, task_id = ts.create_task(
                            title=title,
                            description=description,
                            department_id=dept_options[dept_name],
                            assigned_to=assignee_options[assignee_name],
                            created_by=user["user_id"],
                            priority=priority,
                            deadline=deadline.isoformat(),
                        )
                        if success:
                            st.success(msg)
                            st.rerun()
                        else:
                            st.error(msg)

    st.markdown("<br>", unsafe_allow_html=True)
    section_label("Filters")

    fcol1, fcol2, fcol3, fcol4 = st.columns(4)
    with fcol1:
        search_q = st.text_input("🔎 Search title, code, description", key="search_q")
    with fcol2:
        depts_all = list_departments()
        dept_filter_options = ["All Departments"] + [d["department_name"] for d in depts_all]
        dept_filter = st.selectbox("Department", dept_filter_options)
    with fcol3:
        status_filter = st.selectbox("Status", ["All Statuses"] + ts.ALL_STATUSES)
    with fcol4:
        priority_filter = st.selectbox("Priority", ["All Priorities"] + ts.PRIORITIES)

    dept_id_filter = None
    if dept_filter != "All Departments":
        dept_id_filter = next(d["department_id"] for d in depts_all if d["department_name"] == dept_filter)

    assigned_filter = None if is_president else user["user_id"]

    tasks = ts.list_tasks(
        department_id=dept_id_filter,
        assigned_to=assigned_filter,
        status=None if status_filter == "All Statuses" else status_filter,
        priority=None if priority_filter == "All Priorities" else priority_filter,
        search=search_q if search_q else None,
    )

    sort_choice = st.radio(
        "Sort by", ["Deadline (soonest first)", "Priority (high first)", "Newest first"],
        horizontal=True, label_visibility="collapsed",
    )
    if sort_choice == "Priority (high first)":
        order = {"High": 0, "Medium": 1, "Low": 2}
        tasks = sorted(tasks, key=lambda t: order.get(t["priority"], 3))
    elif sort_choice == "Newest first":
        tasks = sorted(tasks, key=lambda t: t["created_at"], reverse=True)

    st.markdown(f"**{len(tasks)} task(s) found**")
    st.markdown("<br>", unsafe_allow_html=True)

    if not tasks:
        st.info("No tasks match your filters.")
    else:
        for t in tasks:
            overdue = ts.is_overdue(t)
            with st.container(border=True):
                c1, c2 = st.columns([5, 1])
                with c1:
                    overdue_badge = ' <span class="dc-badge" style="--badge-color:#E63946">⚠ Overdue</span>' if overdue else ""
                    st.markdown(
                        f"""
                        <div class="dc-task-code">{t['task_code']} · {t['department_name']}</div>
                        <div class="dc-task-title" style="font-size:16px;">{t['title']}</div>
                        <div class="dc-meta-row">
                            {priority_badge_html(t['priority'])}
                            {status_badge_html(t['status'])}
                            {overdue_badge}
                        </div>
                        <div style="margin-top:6px; font-size:12.5px; color:var(--text-muted);">
                            👤 {t['assigned_to_name'] or 'Unassigned'} &nbsp;·&nbsp; 📅 Due {t['deadline']}
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )
                with c2:
                    if st.button("Open →", key=f"open_{t['task_id']}", width='stretch'):
                        st.session_state["selected_task_id"] = t["task_id"]
                        st.session_state["upload_done"] = False
                        st.query_params["task_id"] = str(t["task_id"])
                        st.rerun()
