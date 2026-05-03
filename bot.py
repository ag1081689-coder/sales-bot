    if "|" in user_message:
        lines = user_message.strip().split("\n")
        responses = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            parts = line.split("|")
            if len(parts) == 3:
                project = parts[0].strip()
                field = parts[1].strip()
                value = parts[2].strip()
                if any(p.lower() == project.lower() for p in PROJECTS):
                    matched = next(p for p in PROJECTS if p.lower() == project.lower())
                    result = write_to_sheet(matched, field, value)
                    responses.append(f"{result}: {field} في {matched}")
                else:
                    responses.append(f"مش لاقي المشروع: {project}")
        if responses:
            await update.message.reply_text("\n".join(responses))
        return
