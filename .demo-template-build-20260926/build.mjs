import fs from 'node:fs/promises';
import {Presentation,PresentationFile} from '@oai/artifact-tool';
import {finalizePresentation} from '/Users/nakamineshinma/.codex/plugins/cache/openai-primary-runtime/presentations/26.909.12148/skills/presentations/container_tools/artifact_tool_utils.mjs';
const root='/Users/nakamineshinma/Desktop/ETHGlobalTokyo/team_codrea_ethglocal';
const build=root+'/.demo-template-build-20260926';
const out=root+'/deliverables/ethglobal-demo-template-20260926';
const skill='/Users/nakamineshinma/.codex/plugins/cache/openai-primary-runtime/presentations/26.909.12148/skills/presentations';
const p=Presentation.create({slideSize:{width:1280,height:720}});
const font='Arial';
const ink='#F4F2EA', muted='#B5BDB9', accent='#C4F277', bg='#132521';
function text(s,str,x,y,w,h,size=28,color=ink,bold=false){const t=s.shapes.add({geometry:'textbox',position:{left:x,top:y,width:w,height:h},fill:'none',line:{fill:'none',width:0}});t.text=str;t.text.style={typeface:font,fontSize:size,color,bold,autoFit:'none'};return t;}
function slide(n,title,notes){const s=p.slides.add();s.background.fill=bg;text(s,title,72,64,1136,120,48,ink,true);text(s,`CHOICE / ETHGLOBAL TOKYO`,72,662,750,25,16,muted);text(s,String(n).padStart(2,'0'),1140,660,70,28,18,accent);s.speakerNotes.textFrame.setText(notes+'\n\n出典: README.md、contracts/src/Escrow.sol（2026-09-26 読み取り）。テンプレート内の [ ] は差し替え項目。実機連携・成功実績は未検証。');return s;}
let s=slide(1,'Choice','15秒。「Choiceは、AIが案件を進め、人間が重要な判断を担うB2Bマーケットプレイスです」。チーム名と一文説明を確定する。');
text(s,'AI agent marketplace\nwith human approval',72,240,1100,170,64,ink,true);text(s,'[Team name]   /   ETHGlobal Tokyo',76,540,1000,50,26,accent);
s=slide(2,'The trust gap in AI work','20秒。課題仮説として説明。「AIに作業を任せられても、誰に依頼するか、成果物を誰が判断するか、いつ支払うかは残ります」。顧客調査や市場規模は未確認のため断定しない。');
text(s,'Who is behind the agent?',72,230,1100,60,38);text(s,'Who accepts the work?',72,325,1100,60,38);text(s,'What authorizes payment?',72,420,1100,60,38);text(s,'[Add one concrete customer situation]',72,560,1100,45,24,accent);
s=slide(3,'How Choice works','20秒。「PM Agentが依頼を工程に分解し、AIと人間に振り分けます。人間が成果物を承認し、必要な署名がそろった工程からEscrowが支払います」。ENS名は権限を付与しない。World IDは専門能力を保証しない。');
text(s,'AI organizes and produces the work',72,230,1100,65,39,ink,true);text(s,'People approve deliverables and handle human tasks',72,325,1100,75,31);text(s,'Escrow pays when the approval threshold is met',72,435,1100,80,31,accent);
s=slide(4,'Live demo','75秒。例: 新店舗のWebページ用コンテンツを依頼し、AIが原稿を生成、人間が現地情報を確認する。実際の機能に合う1案件へ差し替える。Agent選択10秒、計画15秒、人間確認と成果物20秒、承認と支払い30秒。World確認など待ち時間の長い部分は事前準備し、省略を明示する。画面にmock表示があれば口頭で明示する。');
text(s,'[Customer request in one sentence]',72,200,1100,70,32,accent);text(s,'[Replace this area with an actual screenshot]\n\nAgent profile / task plan / delivery / payment',72,310,1090,200,30,muted);text(s,'Choose an agent     Plan the work     Review     Approve',72,565,1100,50,27);
s=slide(5,'Why World, ENS and escrow','25秒。Worldは重要操作に人間確認を使い、ENSはAgentの名前と公開プロフィールを共有する。Escrowは固定承認者の署名と承認数を検証する。運用ワーカーが送信する構成で、完全な分散型仲裁ではない。カスタムENS配下の評価更新には委任の制約がある。');
for(const [i,a,b] of [[0,'World ID','Human verification for key actions'],[1,'ENS','Agent names and public profiles'],[2,'Escrow','Task payment after signed approval']]){text(s,a,72,225+i*112,260,60,35,accent,true);text(s,b,370,228+i*112,820,65,30);}
s=slide(6,'What the demo proves','15秒。実際に確認した結果だけ記入する。未記入のまま本番で使用しない。数値は計測していなければ載せない。SepoliaとMock USDCを明示し、モックと実連携を区別する。');
text(s,'Completed flow',72,225,300,55,29,accent,true);text(s,'[Verified start and end state]',395,225,805,65,29);text(s,'Evidence',72,335,300,55,29,accent,true);text(s,'[Transaction link / ENS record / screenshot]',395,335,805,85,28);text(s,'Demo mode',72,465,300,55,29,accent,true);text(s,'[Live integrations]   [Mock integrations]',395,465,805,80,28);text(s,'Prototype environment: Sepolia / Mock USDC',72,590,1100,40,23,muted);
s=slide(7,'Choice','10秒。「AIに仕事を任せ、人間の判断で完了させる。その一連の体験がChoiceです」。デモURL・リポジトリURLと次の開発目標を差し替える。');
text(s,'AI work. Human approval.',72,230,1130,110,62,ink,true);text(s,'[Demo URL]\n[Repository URL]',76,400,1100,110,28,accent);text(s,'Next: [One concrete milestone]',76,570,1100,50,27);
s=slide(8,'Appendix / implementation','質疑応答用。本編には含めない。Next.jsからFastAPIへ要求を送り、Geminiが計画・生成を担う。PostgreSQLに案件等を保存し、ワーカーがENSとEscrowを更新する。World検証はAPIで行う。署名承認者と必要数はopenCaseで固定。Jury結果の反映はonlyOpsのresolveで実行する。READMEと旧仕様書で資金フローが異なるため、READMEと現在のEscrow.solを優先した。');
text(s,'App',72,220,250,55,30,accent,true);text(s,'Next.js / FastAPI / PostgreSQL',350,220,850,65,30);text(s,'Agent',72,320,250,55,30,accent,true);text(s,'Gemini plans tasks and generates deliverables',350,320,850,75,28);text(s,'Identity',72,425,250,55,30,accent,true);text(s,'World verification / ENS profiles',350,425,850,65,30);text(s,'Settlement',72,525,250,55,30,accent,true);text(s,'Operations worker / EIP-712 / task escrow',350,525,850,80,28);
s=slide(9,'Appendix / recorded demo','回線・ウォレット・外部APIの不調時は20秒以内に切り替える。「こちらは同じフローの事前録画です」と説明する。実画面を配置する。録画もモックか実連携かを明示する。保存先をオフラインで開けるようにする。');
text(s,'[Recorded demo file or URL]',72,205,1100,65,30,accent);text(s,'[Replace with a screenshot of the final state]',72,330,1100,140,31,muted);text(s,'[Verified result]   /   [Live or mock mode]',72,555,1100,60,28);
await (await PresentationFile.exportPptx(p)).save(build+'/candidate.pptx');
await finalizePresentation({workspaceDir:root,candidatePath:build+'/candidate.pptx',finalPath:out+'/Choice_ETHGlobal_Demo_Template.pptx',pythonExecutable:'/Users/nakamineshinma/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3',integrityValidatorPath:skill+'/container_tools/inspect_presentation_package_integrity.py',layoutValidatorPath:skill+'/container_tools/inspect_presentation_layout_geometry.py',layoutArgs:['--expected-slide-size-emu','12192000,6858000','--validate-bullet-geometry','--validate-heading-fit'],fontPolicy:{basis:'design',families:[font]},verifyArtifactToolImport:true,receiptPath:build+'/validation.json'});
for(let i=0;i<p.slides.items.length;i++){const b=await p.export({slide:p.slides.items[i],format:'png',scale:1});await fs.writeFile(build+`/slide-${i+1}.png`,new Uint8Array(await b.arrayBuffer()));}
console.log('Created and rendered '+p.slides.items.length+' slides');
