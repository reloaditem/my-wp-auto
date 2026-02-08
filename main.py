for line in lines:
            if any(x in line for x in ["Title:", "Keywords:"]): continue
            clean_line = line.replace("**", "").replace("#", "").strip()
            if not clean_line: continue
            
            # --- 소제목 판별 기준 대폭 완화 및 강화 ---
            # 1. 60자 미만의 짧은 줄이거나
            # 2. 숫자로 시작하거나 (1. 2. ...)
            # 3. 콜론(:)으로 끝나면 무조건 소제목 스타일 적용
            is_heading = (len(clean_line) < 60) or clean_line[0].isdigit() or clean_line.endswith(':')

            if is_heading:
                # 숫자나 특수문자 제거 후 깔끔하게 텍스트만 추출
                pure_text = clean_line.lstrip("0123456789. ").strip(" :")
                content_parts.append(
                    f'<h2 style="color: #1a2a6c; margin: 45px 0 20px 0; '
                    f'border-left: 10px solid #f2a365; padding-left: 15px; '
                    f'font-weight: bold; line-height: 1.3; font-size: 1.6em;">'
                    f'{pure_text}</h2>'
                )
            else:
                content_parts.append(
                    f'<p style="line-height: 1.9; margin-bottom: 25px; '
                    f'font-size: 1.15em; color: #333; text-align: justify;">'
                    f'{clean_line}</p>'
                )
